package main

import (
	"fmt"

	"github.com/spf13/cobra"
)

var versionCmd = &cobra.Command{
	Use:   "version",
	Short: "Show version information",
	Long:  "Display the version of the agent CLI tool",
	Run: func(cmd *cobra.Command, args []string) {
		fmt.Printf("agent version %s (P2 milestone)\n", version)
		fmt.Println("Built for Asterisk AI Voice Agent")
		fmt.Println("https://github.com/hkjarral/asterisk-ai-voice-agent")
	},
}

func init() {
	rootCmd.AddCommand(versionCmd)
}
