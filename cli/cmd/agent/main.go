package main

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

var (
	version = "1.0.0-p2-dev"
	verbose bool
)

func main() {
	if err := rootCmd.Execute(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

var rootCmd = &cobra.Command{
	Use:   "agent",
	Short: "Asterisk AI Voice Agent CLI",
	Long: `Asterisk AI Voice Agent CLI - Tools for setup, health checks, and troubleshooting

Available commands:
  init        Interactive setup wizard
  doctor      System health check and diagnostics
  demo        Audio pipeline validation
  troubleshoot Post-call analysis and RCA
  version     Show version information`,
	SilenceUsage:  true,
	SilenceErrors: true,
}

func init() {
	rootCmd.PersistentFlags().BoolVarP(&verbose, "verbose", "v", false, "verbose output")
}
