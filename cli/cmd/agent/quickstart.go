package main

import (
	"bufio"
	"fmt"
	"os"
	"strings"

	"github.com/hkjarral/asterisk-ai-voice-agent/cli/internal/dialplan"
	"github.com/hkjarral/asterisk-ai-voice-agent/cli/internal/validator"
	"github.com/spf13/cobra"
)

var quickstartCmd = &cobra.Command{
	Use:   "quickstart",
	Short: "Interactive setup wizard for first-time users",
	Long: `Interactive wizard that guides you through:
  1. Provider selection
  2. API key validation
  3. ARI connection test
  4. Configuration generation
  5. Docker startup
  6. Dialplan snippet generation
  7. Optional health check

This command is designed for first-time users to get up and running quickly.`,
	RunE: runQuickstart,
}

func init() {
	rootCmd.AddCommand(quickstartCmd)
}

func runQuickstart(cmd *cobra.Command, args []string) error {
	fmt.Println("")
	fmt.Println("╔══════════════════════════════════════════════════════════╗")
	fmt.Println("║   Asterisk AI Voice Agent - Quickstart Wizard           ║")
	fmt.Println("╚══════════════════════════════════════════════════════════╝")
	fmt.Println("")
	fmt.Println("This wizard will help you:")
	fmt.Println("  • Select and configure your AI provider")
	fmt.Println("  • Validate API keys")
	fmt.Println("  • Test Asterisk ARI connection")
	fmt.Println("  • Generate dialplan configuration")
	fmt.Println("  • Start Docker containers")
	fmt.Println("")
	
	reader := bufio.NewReader(os.Stdin)
	
	// Step 1: Provider Selection
	fmt.Println("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
	fmt.Println("Step 1: Provider Selection")
	fmt.Println("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
	fmt.Println("")
	fmt.Println("Available providers:")
	fmt.Println("  1) OpenAI Realtime    - Full-duplex, natural conversations (requires API key)")
	fmt.Println("  2) Deepgram           - Fast, accurate transcription (requires API key)")
	fmt.Println("  3) Google Live API    - Multimodal capabilities (requires API key)")
	fmt.Println("  4) Local Hybrid       - Runs entirely on-premise (no API key needed)")
	fmt.Println("")
	
	fmt.Print("Select provider [1-4]: ")
	choice, _ := reader.ReadString('\n')
	choice = strings.TrimSpace(choice)
	
	provider := ""
	needsAPIKey := true
	
	switch choice {
	case "1":
		provider = "openai_realtime"
		fmt.Println("✓ Selected: OpenAI Realtime")
	case "2":
		provider = "deepgram"
		fmt.Println("✓ Selected: Deepgram")
	case "3":
		provider = "google_live"
		fmt.Println("✓ Selected: Google Live API")
	case "4":
		provider = "local_hybrid"
		needsAPIKey = false
		fmt.Println("✓ Selected: Local Hybrid (no API key required)")
	default:
		return fmt.Errorf("invalid selection: %s", choice)
	}
	
	fmt.Println("")
	
	// Step 2: API Key Validation (if needed)
	var apiKey string
	if needsAPIKey {
		fmt.Println("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
		fmt.Println("Step 2: API Key Validation")
		fmt.Println("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
		fmt.Println("")
		
		switch provider {
		case "openai_realtime":
			fmt.Println("Get your API key from: https://platform.openai.com/api-keys")
		case "deepgram":
			fmt.Println("Get your API key from: https://console.deepgram.com/")
		case "google_live":
			fmt.Println("Get your API key from: https://console.cloud.google.com/")
		}
		
		fmt.Println("")
		fmt.Print("Enter API key: ")
		apiKey, _ = reader.ReadString('\n')
		apiKey = strings.TrimSpace(apiKey)
		
		if apiKey == "" {
			return fmt.Errorf("API key cannot be empty")
		}
		
		// Validate API key
		fmt.Print("Validating API key... ")
		if err := validator.ValidateAPIKey(provider, apiKey); err != nil {
			fmt.Println("❌")
			fmt.Println("")
			fmt.Printf("API key validation failed: %v\n", err)
			fmt.Println("")
			fmt.Println("Please check:")
			fmt.Println("  • API key is correct")
			fmt.Println("  • Internet connection is working")
			fmt.Println("  • Provider service is accessible")
			fmt.Println("")
			fmt.Println("Re-run 'agent quickstart' to try again")
			return fmt.Errorf("API key validation failed")
		}
		
		fmt.Println("✓")
		fmt.Println("")
	}
	
	// Step 3: ARI Connection
	fmt.Println("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
	fmt.Println("Step 3: Asterisk ARI Connection")
	fmt.Println("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
	fmt.Println("")
	
	fmt.Print("Asterisk host [localhost]: ")
	asteriskHost, _ := reader.ReadString('\n')
	asteriskHost = strings.TrimSpace(asteriskHost)
	if asteriskHost == "" {
		asteriskHost = "localhost"
	}
	
	fmt.Print("ARI username [asterisk]: ")
	ariUser, _ := reader.ReadString('\n')
	ariUser = strings.TrimSpace(ariUser)
	if ariUser == "" {
		ariUser = "asterisk"
	}
	
	fmt.Print("ARI password: ")
	ariPassword, _ := reader.ReadString('\n')
	ariPassword = strings.TrimSpace(ariPassword)
	
	fmt.Println("")
	fmt.Printf("Testing ARI connection to %s...\n", asteriskHost)
	fmt.Println("⚠️  ARI validation not yet implemented in quickstart")
	fmt.Println("   Connection will be tested when containers start")
	fmt.Println("")
	
	// Step 4: Generate Configuration
	fmt.Println("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
	fmt.Println("Step 4: Configuration")
	fmt.Println("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
	fmt.Println("")
	
	fmt.Println("Configuration will be saved to:")
	fmt.Println("  • .env (credentials)")
	fmt.Println("  • config/ai-agent.yaml (AI settings)")
	fmt.Println("")
	
	fmt.Print("Continue? [Y/n]: ")
	confirm, _ := reader.ReadString('\n')
	confirm = strings.TrimSpace(confirm)
	
	if strings.ToLower(confirm) == "n" {
		fmt.Println("Quickstart cancelled")
		return nil
	}
	
	// Save configuration
	fmt.Println("⚠️  Configuration generation not yet fully implemented")
	fmt.Println("   Please use 'agent init' or edit files manually")
	fmt.Println("")
	
	// Step 5: Dialplan Generation
	fmt.Println("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
	fmt.Println("Step 5: Dialplan Configuration")
	fmt.Println("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
	fmt.Println("")
	
	snippet := dialplan.GenerateSnippet(provider)
	providerName := dialplan.GetProviderDisplayName(provider)
	
	fmt.Printf("Add this dialplan snippet to /etc/asterisk/extensions_custom.conf:\n")
	fmt.Println("")
	fmt.Println("────────────────────────────────────────────────────────────")
	fmt.Println(snippet)
	fmt.Println("────────────────────────────────────────────────────────────")
	fmt.Println("")
	fmt.Println("FreePBX users:")
	fmt.Println("  1. Admin → Config Edit → extensions_custom.conf")
	fmt.Println("  2. Paste snippet above")
	fmt.Println("  3. Admin → Custom Destination → Add")
	contextName := getContextName(provider)
	fmt.Printf("     Target: %s,s,1\n", contextName)
	fmt.Printf("     Description: AI Voice Agent - %s\n", providerName)
	fmt.Println("")
	
	// Step 6: Summary
	fmt.Println("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
	fmt.Println("Setup Complete!")
	fmt.Println("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
	fmt.Println("")
	fmt.Println("Next steps:")
	fmt.Println("  1. Add dialplan snippet to Asterisk (see above)")
	fmt.Println("  2. Start Docker containers:")
	fmt.Println("     docker compose up -d")
	fmt.Println("  3. Check health:")
	fmt.Println("     agent doctor")
	fmt.Println("  4. Make a test call!")
	fmt.Println("")
	fmt.Println("For detailed setup instructions, see:")
	fmt.Println("  docs/CLI_TOOLS_GUIDE.md")
	fmt.Println("  docs/FreePBX-Integration-Guide.md")
	fmt.Println("")
	
	return nil
}
