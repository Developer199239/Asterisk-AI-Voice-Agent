package main

import (
	"fmt"

	"github.com/spf13/cobra"
)

var (
	initNonInteractive bool
	initTemplate       string
)

var initCmd = &cobra.Command{
	Use:   "init",
	Short: "Interactive setup wizard",
	Long: `Interactive setup wizard for Asterisk AI Voice Agent.

Guides you through configuration:
  - Asterisk ARI credentials
  - Audio transport (AudioSocket/ExternalMedia)
  - AI provider selection (OpenAI, Deepgram, Anthropic, etc.)
  - Pipeline configuration
  - Configuration validation

This can be run multiple times to reconfigure the system.`,
	RunE: func(cmd *cobra.Command, args []string) error {
		fmt.Println()
		fmt.Println("🚀 Asterisk AI Voice Agent - Setup Wizard")
		fmt.Println("══════════════════════════════════════════")
		fmt.Println()
		fmt.Println("This wizard will help you configure your AI voice agent.")
		fmt.Println()
		
		// TODO: Implement full wizard
		fmt.Println("⚠️  This command is under development.")
		fmt.Println()
		fmt.Println("For now, please use ./install.sh for initial setup.")
		fmt.Println()
		fmt.Println("Coming soon:")
		fmt.Println("  • Interactive configuration wizard")
		fmt.Println("  • API key validation")
		fmt.Println("  • ARI connectivity testing")
		fmt.Println("  • Pipeline selection")
		fmt.Println("  • Configuration generation")
		fmt.Println()
		
		return nil
	},
}

func init() {
	initCmd.Flags().BoolVar(&initNonInteractive, "non-interactive", false, "non-interactive mode (use defaults)")
	initCmd.Flags().StringVar(&initTemplate, "template", "", "config template: local|cloud|hybrid|openai-agent|deepgram-agent")
	
	rootCmd.AddCommand(initCmd)
}
