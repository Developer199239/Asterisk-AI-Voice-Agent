package main

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/hkjarral/asterisk-ai-voice-agent/cli/internal/check"
	"github.com/spf13/cobra"
)

type rebuildMode string

const (
	rebuildAuto rebuildMode = "auto"
	rebuildNone rebuildMode = "none"
	rebuildAll  rebuildMode = "all"
)

var (
	updateRemote        string
	updateRef           string
	updateNoStash       bool
	updateStashUntracked bool
	updateRebuild       string
	updateForceRecreate bool
	updateSkipCheck     bool
)

var updateCmd = &cobra.Command{
	Use:   "update",
	Short: "Pull latest code and apply updates",
	Long: `Update Asterisk AI Voice Agent to the latest code and apply changes safely.

This command:
  - Backs up operator-owned config (.env, config/ai-agent.yaml, config/contexts/)
  - Safely fast-forwards to origin/main (no forced merges by default)
  - Preserves local tracked changes using git stash (optional)
  - Rebuilds/restarts only the containers impacted by the change set
  - Verifies success by running agent check (optional)

Safety notes:
  - No hard resets are performed.
  - Fast-forward only: if your branch has diverged, the update stops with guidance.`,
	RunE: func(cmd *cobra.Command, args []string) error {
		return runUpdate()
	},
}

func init() {
	updateCmd.Flags().StringVar(&updateRemote, "remote", "origin", "git remote name")
	updateCmd.Flags().StringVar(&updateRef, "ref", "main", "git ref/branch to update to (e.g., main)")
	updateCmd.Flags().BoolVar(&updateNoStash, "no-stash", false, "abort if repo has local changes instead of stashing")
	updateCmd.Flags().BoolVar(&updateStashUntracked, "stash-untracked", false, "include untracked files when stashing (does not include ignored files)")
	updateCmd.Flags().StringVar(&updateRebuild, "rebuild", string(rebuildAuto), "rebuild mode: auto|none|all")
	updateCmd.Flags().BoolVar(&updateForceRecreate, "force-recreate", false, "force recreate containers during docker compose up")
	updateCmd.Flags().BoolVar(&updateSkipCheck, "skip-check", false, "skip running agent check after update")
	rootCmd.AddCommand(updateCmd)
}

type updateContext struct {
	repoRoot string
	oldSHA   string
	newSHA   string
	backupDir string
	stashed  bool
	stashRef string

	changedFiles []string

	servicesToRebuild map[string]bool
	servicesToRestart map[string]bool
	composeChanged    bool
}

func runUpdate() error {
	repoRoot, err := gitShowTopLevel()
	if err != nil {
		return err
	}
	if err := os.Chdir(repoRoot); err != nil {
		return fmt.Errorf("failed to chdir to repo root: %w", err)
	}

	ctx := &updateContext{
		repoRoot:          repoRoot,
		servicesToRebuild: map[string]bool{},
		servicesToRestart: map[string]bool{},
	}

	ctx.oldSHA, err = gitRevParse("HEAD")
	if err != nil {
		return err
	}

	if err := createUpdateBackups(ctx); err != nil {
		return err
	}

	dirty, err := gitIsDirty(updateStashUntracked)
	if err != nil {
		return err
	}
	if dirty {
		if updateNoStash {
			return errors.New("working tree has local changes; re-run without --no-stash or commit your changes first")
		}
		if err := gitStash(ctx, updateStashUntracked); err != nil {
			return err
		}
	}

	if err := gitFetch(updateRemote, updateRef); err != nil {
		return err
	}
	ctx.newSHA, err = gitRevParse(fmt.Sprintf("%s/%s", updateRemote, updateRef))
	if err != nil {
		return err
	}

	if ctx.newSHA == ctx.oldSHA {
		if ctx.stashed {
			if err := gitStashPop(ctx); err != nil {
				return err
			}
		}
		if updateSkipCheck {
			fmt.Printf("Already up to date (%s)\n", shortSHA(ctx.oldSHA))
			return nil
		}

		status, warnCount, failCount, err := runPostUpdateCheck()
		printUpdateSummary(ctx, status, warnCount, failCount)
		if err != nil {
			return err
		}
		if failCount > 0 {
			return errors.New("post-update check reported failures")
		}
		return nil
	}

	if err := gitMergeFastForward(fmt.Sprintf("%s/%s", updateRemote, updateRef)); err != nil {
		return err
	}

	if ctx.stashed {
		if err := gitStashPop(ctx); err != nil {
			return err
		}
	}

	ctx.changedFiles, err = gitDiffNames(ctx.oldSHA, ctx.newSHA)
	if err != nil {
		return err
	}
	decideDockerActions(ctx)

	if err := applyDockerActions(ctx); err != nil {
		return err
	}

	if updateSkipCheck {
		printUpdateSummary(ctx, "", 0, 0)
		return nil
	}

	status, warnCount, failCount, err := runPostUpdateCheck()
	printUpdateSummary(ctx, status, warnCount, failCount)
	if err != nil {
		return err
	}
	if failCount > 0 {
		return errors.New("post-update check reported failures")
	}
	return nil
}

func createUpdateBackups(ctx *updateContext) error {
	timestamp := time.Now().UTC().Format("20060102_150405")
	backupDir := filepath.Join(ctx.repoRoot, ".agent", "update-backups", timestamp)
	if err := os.MkdirAll(backupDir, 0o755); err != nil {
		return fmt.Errorf("failed to create backup directory: %w", err)
	}
	ctx.backupDir = backupDir

	paths := []string{
		".env",
		filepath.Join("config", "ai-agent.yaml"),
		filepath.Join("config", "contexts"),
	}

	for _, rel := range paths {
		if err := backupPathIfExists(rel, backupDir); err != nil {
			return err
		}
	}
	return nil
}

func backupPathIfExists(relPath string, backupRoot string) error {
	info, err := os.Stat(relPath)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return fmt.Errorf("failed to stat %s: %w", relPath, err)
	}
	dst := filepath.Join(backupRoot, relPath)
	if info.IsDir() {
		return copyDir(relPath, dst)
	}
	return copyFile(relPath, dst)
}

func copyFile(src string, dst string) error {
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return fmt.Errorf("failed to create backup dir for %s: %w", dst, err)
	}
	in, err := os.Open(src)
	if err != nil {
		return fmt.Errorf("failed to open %s: %w", src, err)
	}
	defer in.Close()

	out, err := os.Create(dst)
	if err != nil {
		return fmt.Errorf("failed to create %s: %w", dst, err)
	}
	defer func() {
		_ = out.Close()
	}()
	if _, err := io.Copy(out, in); err != nil {
		return fmt.Errorf("failed to copy %s -> %s: %w", src, dst, err)
	}
	if err := out.Sync(); err != nil {
		return fmt.Errorf("failed to sync %s: %w", dst, err)
	}
	return nil
}

func copyDir(srcDir string, dstDir string) error {
	return filepath.WalkDir(srcDir, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(srcDir, path)
		if err != nil {
			return err
		}
		dstPath := filepath.Join(dstDir, rel)
		if entry.IsDir() {
			return os.MkdirAll(dstPath, 0o755)
		}
		if entry.Type()&os.ModeSymlink != 0 {
			// Skip symlinks in backups; they are uncommon here and can point outside the repo.
			return nil
		}
		return copyFile(path, dstPath)
	})
}

func gitShowTopLevel() (string, error) {
	out, err := runCmd("git", "rev-parse", "--show-toplevel")
	if err != nil {
		return "", fmt.Errorf("not a git repository (or git not installed): %w", err)
	}
	return strings.TrimSpace(out), nil
}

func gitRevParse(ref string) (string, error) {
	out, err := runCmd("git", "rev-parse", ref)
	if err != nil {
		return "", fmt.Errorf("git rev-parse %s failed: %w", ref, err)
	}
	return strings.TrimSpace(out), nil
}

func gitIsDirty(includeUntracked bool) (bool, error) {
	args := []string{"status", "--porcelain"}
	if includeUntracked {
		args = append(args, "--untracked-files=all")
	}
	out, err := runCmd("git", args...)
	if err != nil {
		return false, fmt.Errorf("git status failed: %w", err)
	}
	return strings.TrimSpace(out) != "", nil
}

func gitStash(ctx *updateContext, includeUntracked bool) error {
	msg := "agent update " + time.Now().UTC().Format(time.RFC3339)
	var err error
	var out string

	if includeUntracked {
		out, err = runCmd("git", "stash", "save", "-u", msg)
	} else {
		out, err = runCmd("git", "stash", "save", msg)
	}
	if err != nil {
		return fmt.Errorf("git stash failed: %w", err)
	}

	// If there was nothing to stash, git prints a message and does not create an entry.
	if strings.Contains(out, "No local changes") {
		return nil
	}

	ctx.stashed = true
	ctx.stashRef = ""
	ref, refErr := runCmd("git", "stash", "list", "-1")
	if refErr == nil {
		ctx.stashRef = strings.TrimSpace(ref)
	}
	return nil
}

func gitStashPop(ctx *updateContext) error {
	_, err := runCmd("git", "stash", "pop")
	if err != nil {
		// On conflict, git typically returns non-zero and leaves the stash in place.
		return fmt.Errorf("git stash pop failed (possible conflicts). Your stash is likely preserved; run `git stash list` and resolve conflicts: %w", err)
	}
	return nil
}

func gitFetch(remote string, ref string) error {
	_, err := runCmd("git", "fetch", remote, ref)
	if err != nil {
		return fmt.Errorf("git fetch %s %s failed: %w", remote, ref, err)
	}
	return nil
}

func gitMergeFastForward(remoteRef string) error {
	_, err := runCmd("git", "merge", "--ff-only", remoteRef)
	if err != nil {
		return fmt.Errorf("git merge --ff-only %s failed (branch likely diverged or local conflicts). Fix manually and retry: %w", remoteRef, err)
	}
	return nil
}

func gitDiffNames(oldSHA string, newSHA string) ([]string, error) {
	out, err := runCmd("git", "diff", "--name-only", oldSHA+".."+newSHA)
	if err != nil {
		return nil, fmt.Errorf("git diff failed: %w", err)
	}
	lines := []string{}
	for _, line := range strings.Split(out, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		lines = append(lines, line)
	}
	sort.Strings(lines)
	return lines, nil
}

func decideDockerActions(ctx *updateContext) {
	mode := rebuildMode(strings.ToLower(strings.TrimSpace(updateRebuild)))
	if mode != rebuildAuto && mode != rebuildNone && mode != rebuildAll {
		mode = rebuildAuto
	}

	for _, f := range ctx.changedFiles {
		if strings.HasPrefix(f, "docker-compose") && (strings.HasSuffix(f, ".yml") || strings.HasSuffix(f, ".yaml")) {
			ctx.composeChanged = true
		}
	}

	if mode == rebuildNone {
		// Conservative: restart ai_engine if code/config changed.
		for _, f := range ctx.changedFiles {
			if strings.HasPrefix(f, "src/") || f == "main.py" || strings.HasPrefix(f, "config/") || strings.HasPrefix(f, "scripts/") {
				ctx.servicesToRestart["ai_engine"] = true
			}
		}
		return
	}

	if mode == rebuildAll {
		ctx.servicesToRebuild["ai_engine"] = true
		ctx.servicesToRebuild["admin_ui"] = true
		ctx.servicesToRebuild["local_ai_server"] = true
		return
	}

	// auto
	for _, f := range ctx.changedFiles {
		switch {
		case strings.HasPrefix(f, "admin_ui/"):
			ctx.servicesToRebuild["admin_ui"] = true
		case strings.HasPrefix(f, "local_ai_server/"):
			ctx.servicesToRebuild["local_ai_server"] = true
		case f == "Dockerfile" || f == "requirements.txt":
			ctx.servicesToRebuild["ai_engine"] = true
		case strings.HasPrefix(f, "src/") || f == "main.py" || strings.HasPrefix(f, "config/") || strings.HasPrefix(f, "scripts/"):
			ctx.servicesToRestart["ai_engine"] = true
		}
	}

	// If we rebuild, restart is implied.
	for svc := range ctx.servicesToRebuild {
		delete(ctx.servicesToRestart, svc)
	}
}

func applyDockerActions(ctx *updateContext) error {
	if len(ctx.servicesToRebuild) == 0 && len(ctx.servicesToRestart) == 0 && !ctx.composeChanged {
		return nil
	}

	if _, err := runCmd("docker", "compose", "version"); err != nil {
		return fmt.Errorf("docker compose is required but not available: %w", err)
	}

	if ctx.composeChanged {
		args := []string{"compose", "up", "-d", "--remove-orphans"}
		if updateForceRecreate {
			args = append(args, "--force-recreate")
		}
		if _, err := runCmd("docker", args...); err != nil {
			return fmt.Errorf("docker compose up (remove-orphans) failed: %w", err)
		}
	}

	rebuildServices := sortedKeys(ctx.servicesToRebuild)
	restartServices := sortedKeys(ctx.servicesToRestart)

	if len(rebuildServices) > 0 {
		args := []string{"compose", "up", "-d", "--build"}
		if updateForceRecreate {
			args = append(args, "--force-recreate")
		}
		args = append(args, rebuildServices...)
		if _, err := runCmd("docker", args...); err != nil {
			return fmt.Errorf("docker compose up --build failed: %w", err)
		}
	}

	for _, svc := range restartServices {
		if _, err := runCmd("docker", "compose", "restart", svc); err != nil {
			// Fallback: start/recreate service if restart fails.
			if _, err2 := runCmd("docker", "compose", "up", "-d", svc); err2 != nil {
				return fmt.Errorf("failed to restart %s (restart error: %v; up error: %w)", svc, err, err2)
			}
		}
	}

	return nil
}

func runPostUpdateCheck() (status string, warnCount int, failCount int, err error) {
	runner := check.NewRunner(verbose, version, buildTime)
	report, runErr := runner.Run()
	if report == nil {
		return "FAIL", 0, 1, fmt.Errorf("agent check failed: %w", runErr)
	}
	warnCount = report.WarnCount
	failCount = report.FailCount
	if runErr != nil || failCount > 0 {
		return "FAIL", warnCount, failCount, runErr
	}
	if warnCount > 0 {
		return "WARN", warnCount, 0, nil
	}
	return "PASS", 0, 0, nil
}

func printUpdateSummary(ctx *updateContext, checkStatus string, warnCount int, failCount int) {
	if strings.TrimSpace(ctx.oldSHA) == strings.TrimSpace(ctx.newSHA) {
		fmt.Printf("Up to date: %s\n", shortSHA(ctx.oldSHA))
	} else {
		fmt.Printf("Updated: %s -> %s\n", shortSHA(ctx.oldSHA), shortSHA(ctx.newSHA))
	}
	if ctx.backupDir != "" {
		fmt.Printf("Backups: %s\n", ctx.backupDir)
	}
	if ctx.stashed {
		if ctx.stashRef != "" {
			fmt.Printf("Stash: %s\n", ctx.stashRef)
		} else {
			fmt.Printf("Stash: created\n")
		}
	}
	if len(ctx.servicesToRebuild) > 0 {
		fmt.Printf("Rebuilt: %s\n", strings.Join(sortedKeys(ctx.servicesToRebuild), ", "))
	}
	if len(ctx.servicesToRestart) > 0 {
		fmt.Printf("Restarted: %s\n", strings.Join(sortedKeys(ctx.servicesToRestart), ", "))
	}
	if ctx.composeChanged {
		fmt.Printf("Compose: applied changes\n")
	}
	if checkStatus != "" {
		fmt.Printf("Check: %s (warn=%d fail=%d)\n", checkStatus, warnCount, failCount)
	}
}

func sortedKeys(m map[string]bool) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

func shortSHA(sha string) string {
	sha = strings.TrimSpace(sha)
	if len(sha) > 8 {
		return sha[:8]
	}
	return sha
}

func runCmd(name string, args ...string) (string, error) {
	cmd := exec.Command(name, args...)
	cmd.Stdin = os.Stdin
	out, err := cmd.CombinedOutput()
	text := strings.TrimSpace(string(out))
	if err != nil {
		if text != "" {
			return text, fmt.Errorf("%w: %s", err, text)
		}
		return text, err
	}
	return text, nil
}
