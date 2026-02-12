package main

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/hkjarral/asterisk-ai-voice-agent/cli/internal/check"
	"github.com/hkjarral/asterisk-ai-voice-agent/cli/internal/configmerge"
)

type fixSummary struct {
	repoRoot     string
	prefixBackup string
	sourceBackup string
	restored     []string
	warnings     []string
}

func runCheckWithFix() error {
	// 1) Baseline diagnostics first (always show operators what failed before fix).
	runner := check.NewRunner(verbose, version, buildTime)
	before, beforeErr := runner.Run()
	if before == nil {
		before = &check.Report{
			Version:   version,
			BuildTime: buildTime,
			Timestamp: time.Now(),
			Items: []check.Item{
				{
					Name:    "agent check",
					Status:  check.StatusFail,
					Message: "failed to generate diagnostics report",
					Details: "unknown error",
				},
			},
		}
	}
	before.OutputText(os.Stdout)

	noIssues := beforeErr == nil && before.FailCount == 0 && before.WarnCount == 0
	if noIssues {
		fmt.Println("No issues detected. No recovery actions needed.")
		return nil
	}

	fmt.Println("Attempting automatic recovery from recent backups...")
	summary, fixErr := runBackupRecovery()
	if summary != nil {
		printFixSummary(summary)
	}
	if fixErr != nil {
		return fixErr
	}

	// Give services a moment to transition after compose restart/up.
	time.Sleep(2 * time.Second)

	fmt.Println("")
	fmt.Println("Re-running diagnostics after fix...")
	after, afterErr := runner.Run()
	if after == nil {
		return errors.New("post-fix diagnostics failed: report unavailable")
	}
	after.OutputText(os.Stdout)

	if afterErr != nil || after.FailCount > 0 {
		os.Exit(2)
	}
	if after.WarnCount > 0 {
		os.Exit(1)
	}
	return nil
}

func runBackupRecovery() (*fixSummary, error) {
	repoRoot, err := resolveRepoRootForFix()
	if err != nil {
		return nil, err
	}
	if err := os.Chdir(repoRoot); err != nil {
		return nil, fmt.Errorf("failed to switch to repo root: %w", err)
	}

	summary := &fixSummary{repoRoot: repoRoot}

	// Safety: snapshot current operator state before touching anything.
	ts := time.Now().UTC().Format("20060102_150405")
	prefixBackup := filepath.Join(repoRoot, ".agent", "check-fix-backups", ts)
	if err := os.MkdirAll(prefixBackup, 0o755); err != nil {
		return summary, fmt.Errorf("failed to create pre-fix backup directory: %w", err)
	}
	summary.prefixBackup = prefixBackup
	for _, rel := range []string{
		".env",
		filepath.Join("config", "ai-agent.yaml"),
		filepath.Join("config", "ai-agent.local.yaml"),
		filepath.Join("config", "users.json"),
		filepath.Join("config", "contexts"),
	} {
		if err := backupPathIfExists(rel, prefixBackup); err != nil {
			return summary, fmt.Errorf("failed to snapshot current state (%s): %w", rel, err)
		}
	}

	restored, source, warns, err := restoreFromUpdateBackups()
	summary.warnings = append(summary.warnings, warns...)
	if err == nil && restored > 0 {
		summary.sourceBackup = source
	} else {
		// Fallback to Admin UI style per-file *.bak snapshots when update backups are unavailable.
		restored, source, warns, err = restoreFromFileBackups()
		summary.warnings = append(summary.warnings, warns...)
		if err == nil && restored > 0 {
			summary.sourceBackup = source
		}
	}
	if err != nil {
		return summary, err
	}

	// Recompute restored list from current actions.
	// (Both restore flows write into checkFixRestoredPaths.)
	summary.restored = append(summary.restored, checkFixRestoredPaths...)
	if len(summary.restored) == 0 {
		return summary, errors.New("no restorable backup files found")
	}

	if err := restartCoreServices(); err != nil {
		return summary, err
	}
	return summary, nil
}

func resolveRepoRootForFix() (string, error) {
	root, err := gitShowTopLevel()
	if err == nil && strings.TrimSpace(root) != "" {
		return root, nil
	}
	wd, wdErr := os.Getwd()
	if wdErr != nil {
		return "", fmt.Errorf("unable to resolve repository root: %w", err)
	}
	return wd, nil
}

var checkFixRestoredPaths []string

func resetFixRestorePaths() {
	checkFixRestoredPaths = nil
}

func noteRestoredPath(path string) {
	checkFixRestoredPaths = append(checkFixRestoredPaths, path)
}

func restoreFromUpdateBackups() (int, string, []string, error) {
	resetFixRestorePaths()
	backupRoot := filepath.Join(".agent", "update-backups")
	entries, err := os.ReadDir(backupRoot)
	if err != nil {
		if os.IsNotExist(err) {
			return 0, "", nil, errors.New("no update backup directories found")
		}
		return 0, "", nil, fmt.Errorf("failed to read update backup root: %w", err)
	}

	type dirInfo struct {
		path string
		mt   time.Time
	}
	dirs := make([]dirInfo, 0, len(entries))
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		full := filepath.Join(backupRoot, e.Name())
		info, statErr := os.Stat(full)
		if statErr != nil {
			continue
		}
		dirs = append(dirs, dirInfo{path: full, mt: info.ModTime()})
	}
	if len(dirs) == 0 {
		return 0, "", nil, errors.New("no update backup directories found")
	}
	sort.Slice(dirs, func(i, j int) bool { return dirs[i].mt.After(dirs[j].mt) })

	var warnings []string
	for _, candidate := range dirs {
		restored, warns := restoreFromSingleBackupDir(candidate.path)
		warnings = append(warnings, warns...)
		if restored > 0 {
			return restored, candidate.path, warnings, nil
		}
	}
	return 0, "", warnings, errors.New("no usable update backup directory found")
}

func restoreFromSingleBackupDir(backupDir string) (int, []string) {
	var warnings []string
	restored := 0

	restoreFile := func(rel string, validate func(string) error, allow bool) {
		if !allow {
			return
		}
		src := filepath.Join(backupDir, rel)
		if _, err := os.Stat(src); err != nil {
			return
		}
		if validate != nil {
			if err := validate(src); err != nil {
				warnings = append(warnings, fmt.Sprintf("Skipped %s from %s: %v", rel, backupDir, err))
				return
			}
		}
		if err := copyFile(src, rel); err != nil {
			warnings = append(warnings, fmt.Sprintf("Failed to restore %s from %s: %v", rel, backupDir, err))
			return
		}
		restored++
		noteRestoredPath(rel)
	}

	restoreBase := shouldRestoreBaseConfig()
	restoreFile(".env", validateEnvBackup, true)
	restoreFile(filepath.Join("config", "ai-agent.local.yaml"), validateYAMLMappingBackup, true)
	restoreFile(filepath.Join("config", "users.json"), nil, true)
	restoreFile(filepath.Join("config", "ai-agent.yaml"), validateYAMLMappingBackup, restoreBase)

	srcCtx := filepath.Join(backupDir, "config", "contexts")
	if info, err := os.Stat(srcCtx); err == nil && info.IsDir() {
		dstCtx := filepath.Join("config", "contexts")
		_ = os.RemoveAll(dstCtx)
		if err := copyDir(srcCtx, dstCtx); err != nil {
			warnings = append(warnings, fmt.Sprintf("Failed to restore config/contexts from %s: %v", backupDir, err))
		} else {
			restored++
			noteRestoredPath(filepath.Join("config", "contexts"))
		}
	}

	return restored, warnings
}

func restoreFromFileBackups() (int, string, []string, error) {
	resetFixRestorePaths()
	var warnings []string
	restored := 0
	sources := map[string]bool{}

	restoreLatest := func(rel string, pattern string, validate func(string) error, allow bool) {
		if !allow {
			return
		}
		src, err := latestBackupMatch(pattern)
		if err != nil {
			warnings = append(warnings, err.Error())
			return
		}
		if src == "" {
			return
		}
		if validate != nil {
			if err := validate(src); err != nil {
				warnings = append(warnings, fmt.Sprintf("Skipped %s from %s: %v", rel, src, err))
				return
			}
		}
		if err := copyFile(src, rel); err != nil {
			warnings = append(warnings, fmt.Sprintf("Failed to restore %s from %s: %v", rel, src, err))
			return
		}
		restored++
		noteRestoredPath(rel)
		sources[filepath.Dir(src)] = true
	}

	restoreLatest(".env", ".env.bak.*", validateEnvBackup, true)
	restoreLatest(filepath.Join("config", "ai-agent.local.yaml"), filepath.Join("config", "ai-agent.local.yaml.bak.*"), validateYAMLMappingBackup, true)
	restoreLatest(filepath.Join("config", "users.json"), filepath.Join("config", "users.json.bak.*"), nil, true)
	restoreLatest(filepath.Join("config", "ai-agent.yaml"), filepath.Join("config", "ai-agent.yaml.bak.*"), validateYAMLMappingBackup, shouldRestoreBaseConfig())

	if restored == 0 {
		return 0, "", warnings, errors.New("no usable backup files found")
	}
	sourceList := sortedKeys(sources)
	return restored, strings.Join(sourceList, ", "), warnings, nil
}

func latestBackupMatch(pattern string) (string, error) {
	matches, err := filepath.Glob(pattern)
	if err != nil {
		return "", fmt.Errorf("invalid backup glob pattern %s: %w", pattern, err)
	}
	if len(matches) == 0 {
		return "", nil
	}
	sort.Slice(matches, func(i, j int) bool {
		iInfo, iErr := os.Stat(matches[i])
		jInfo, jErr := os.Stat(matches[j])
		if iErr != nil || jErr != nil {
			return matches[i] > matches[j]
		}
		return iInfo.ModTime().After(jInfo.ModTime())
	})
	return matches[0], nil
}

func validateYAMLMappingBackup(path string) error {
	if hasConflictMarkers(path) {
		return errors.New("contains git conflict markers")
	}
	if _, err := configmerge.ReadYAMLFile(path); err != nil {
		return fmt.Errorf("invalid YAML mapping: %w", err)
	}
	return nil
}

func validateEnvBackup(path string) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	content := string(data)
	if strings.TrimSpace(content) == "" {
		return errors.New("empty env file")
	}
	// Keep this lightweight: for recovery we only require core ARI keys.
	if !strings.Contains(content, "ASTERISK_HOST=") || !strings.Contains(content, "ASTERISK_ARI_USERNAME=") {
		return errors.New("missing core ARI keys")
	}
	return nil
}

func hasConflictMarkers(path string) bool {
	data, err := os.ReadFile(path)
	if err != nil {
		return false
	}
	content := string(data)
	return strings.Contains(content, "<<<<<<<") || strings.Contains(content, "=======") || strings.Contains(content, ">>>>>>>")
}

func shouldRestoreBaseConfig() bool {
	base := filepath.Join("config", "ai-agent.yaml")
	if _, err := os.Stat(base); err != nil {
		return true
	}
	if hasConflictMarkers(base) {
		return true
	}
	if _, err := configmerge.ReadYAMLFile(base); err != nil {
		return true
	}
	return false
}

func restartCoreServices() error {
	if _, err := runCmd("docker", "compose", "version"); err != nil {
		return fmt.Errorf("docker compose unavailable: %w", err)
	}

	if _, err := runCmd("docker", "compose", "up", "-d", "--no-build", "ai_engine", "admin_ui"); err == nil {
		return nil
	}

	// Fallback path: restart each service and attempt up if restart fails.
	for _, svc := range []string{"ai_engine", "admin_ui"} {
		if _, err := runCmd("docker", "compose", "restart", svc); err != nil {
			if _, err2 := runCmd("docker", "compose", "up", "-d", "--no-build", svc); err2 != nil {
				return fmt.Errorf("failed to restart %s (restart error: %v; up error: %w)", svc, err, err2)
			}
		}
	}
	return nil
}

func printFixSummary(summary *fixSummary) {
	fmt.Println("")
	fmt.Println("Recovery summary")
	fmt.Printf("  Repo root: %s\n", summary.repoRoot)
	if summary.prefixBackup != "" {
		fmt.Printf("  Pre-fix snapshot: %s\n", summary.prefixBackup)
	}
	if summary.sourceBackup != "" {
		fmt.Printf("  Restored from: %s\n", summary.sourceBackup)
	}
	if len(summary.restored) > 0 {
		fmt.Printf("  Restored paths: %s\n", strings.Join(summary.restored, ", "))
	}
	for _, w := range summary.warnings {
		fmt.Printf("  Warning: %s\n", w)
	}
}
