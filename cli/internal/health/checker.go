package health

import (
	"context"
	"fmt"
	"os"
	"time"
)

type CheckStatus string

const (
	StatusPass CheckStatus = "pass"
	StatusWarn CheckStatus = "warn"
	StatusFail CheckStatus = "fail"
	StatusInfo CheckStatus = "info"
)

type Check struct {
	Name        string      `json:"name"`
	Status      CheckStatus `json:"status"`
	Message     string      `json:"message"`
	Details     string      `json:"details,omitempty"`
	Remediation string      `json:"remediation,omitempty"`
}

type HealthResult struct {
	Timestamp     time.Time `json:"timestamp"`
	Checks        []Check   `json:"checks"`
	PassCount     int       `json:"pass_count"`
	WarnCount     int       `json:"warn_count"`
	CriticalCount int       `json:"critical_count"`
	InfoCount     int       `json:"info_count"`
	TotalCount    int       `json:"total_count"`
}

type Checker struct {
	verbose bool
	ctx     context.Context
	envMap  map[string]string
}

func NewChecker(verbose bool) *Checker {
	// Try to load .env file
	envMap, err := LoadEnvFile(".env")
	if err != nil {
		// Try config/.env
		envMap, _ = LoadEnvFile("config/.env")
	}
	
	return &Checker{
		verbose: verbose,
		ctx:     context.Background(),
		envMap:  envMap,
	}
}

func (c *Checker) RunAll() (*HealthResult, error) {
	result := &HealthResult{
		Timestamp: time.Now(),
		Checks:    make([]Check, 0),
	}
	
	// Run all checks in sequence
	checks := []func() Check{
		c.checkDocker,
		c.checkContainers,
		c.checkAsteriskARI,
		c.checkAudioSocket,
		c.checkConfiguration,
		c.checkProviderKeys,
		c.checkAudioPipeline,
		c.checkNetwork,
		c.checkMediaDirectory,
		c.checkLogs,
		c.checkRecentCalls,
	}
	
	for i, checkFn := range checks {
		if c.verbose {
			fmt.Fprintf(os.Stderr, "[%d/%d] Running check...\n", i+1, len(checks))
		}
		check := checkFn()
		result.Checks = append(result.Checks, check)
		
		// Update counters
		switch check.Status {
		case StatusPass:
			result.PassCount++
		case StatusWarn:
			result.WarnCount++
		case StatusFail:
			result.CriticalCount++
		case StatusInfo:
			result.InfoCount++
		}
	}
	
	result.TotalCount = len(result.Checks)
	
	return result, nil
}
