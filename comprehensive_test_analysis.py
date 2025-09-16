#!/usr/bin/env python3
"""
Comprehensive Test Analysis Script
This script will capture all required outputs from inside the container
to verify our findings and determine next steps.
"""

import asyncio
import aiohttp
import json
import logging
import sys
import time
import os
from datetime import datetime
import subprocess

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ComprehensiveTestAnalysis:
    def __init__(self):
        self.ari_base = "http://127.0.0.1:8088/ari"
        self.ari_auth = aiohttp.BasicAuth("AIAgent", "AiAgent+2025?")
        self.app_name = "asterisk-ai-voice-agent"
        self.test_results = {
            "timestamp": datetime.now().isoformat(),
            "test_duration": 0,
            "ari_connectivity": False,
            "channel_creation": False,
            "bridge_creation": False,
            "audiosocket_connection": False,
            "audio_playback": False,
            "stt_processing": False,
            "llm_processing": False,
            "tts_processing": False,
            "errors": [],
            "warnings": [],
            "recommendations": []
        }
        
    async def test_ari_connectivity(self):
        """Test ARI connectivity and basic functionality"""
        logger.info("🔍 Testing ARI Connectivity...")
        try:
            async with aiohttp.ClientSession() as session:
                # Test 1: Get ARI applications
                async with session.get(
                    f"{self.ari_base}/applications",
                    auth=self.ari_auth
                ) as resp:
                    if resp.status == 200:
                        apps = await resp.json()
                        logger.info(f"✅ ARI connected - Found {len(apps)} applications")
                        self.test_results["ari_connectivity"] = True
                        
                        # Check if our app is registered
                        app_names = [app.get('name', '') for app in apps]
                        if self.app_name in app_names:
                            logger.info(f"✅ Stasis app '{self.app_name}' is registered")
                        else:
                            logger.warning(f"⚠️ Stasis app '{self.app_name}' not found in: {app_names}")
                            self.test_results["warnings"].append(f"Stasis app '{self.app_name}' not registered")
                    else:
                        logger.error(f"❌ ARI connection failed: {resp.status}")
                        self.test_results["errors"].append(f"ARI connection failed: {resp.status}")
                        return False
                
                # Test 2: Get channels
                async with session.get(
                    f"{self.ari_base}/channels",
                    auth=self.ari_auth
                ) as resp:
                    if resp.status == 200:
                        channels = await resp.json()
                        logger.info(f"✅ Found {len(channels)} active channels")
                    else:
                        logger.error(f"❌ Failed to get channels: {resp.status}")
                        self.test_results["errors"].append(f"Failed to get channels: {resp.status}")
                
                # Test 3: Get bridges
                async with session.get(
                    f"{self.ari_base}/bridges",
                    auth=self.ari_auth
                ) as resp:
                    if resp.status == 200:
                        bridges = await resp.json()
                        logger.info(f"✅ Found {len(bridges)} active bridges")
                    else:
                        logger.error(f"❌ Failed to get bridges: {resp.status}")
                        self.test_results["errors"].append(f"Failed to get bridges: {resp.status}")
                
                return True
                
        except Exception as e:
            logger.error(f"❌ ARI connectivity test failed: {e}")
            self.test_results["errors"].append(f"ARI connectivity test failed: {e}")
            return False
    
    async def test_channel_creation(self):
        """Test channel creation capabilities"""
        logger.info("🔍 Testing Channel Creation...")
        try:
            async with aiohttp.ClientSession() as session:
                # Test 1: Create a simple Local channel
                channel_data = {
                    "endpoint": "Local/s@ai-agent-media-fork",
                    "channelVars": {"test_var": "test_value"}
                }
                
                async with session.post(
                    f"{self.ari_base}/channels",
                    auth=self.ari_auth,
                    json=channel_data
                ) as resp:
                    if resp.status in [200, 201]:
                        channel_info = await resp.json()
                        channel_id = channel_info["id"]
                        logger.info(f"✅ Local channel created: {channel_id}")
                        self.test_results["channel_creation"] = True
                        
                        # Wait and check channel status
                        await asyncio.sleep(1)
                        async with session.get(
                            f"{self.ari_base}/channels/{channel_id}",
                            auth=self.ari_auth
                        ) as resp:
                            if resp.status == 200:
                                channel_info = await resp.json()
                                logger.info(f"✅ Channel state: {channel_info.get('state', 'unknown')}")
                                logger.info(f"✅ Channel name: {channel_info.get('name', 'unknown')}")
                            else:
                                logger.warning(f"⚠️ Channel disappeared: {resp.status}")
                                self.test_results["warnings"].append(f"Local channel disappeared after creation: {resp.status}")
                        
                        return channel_id
                    else:
                        error_text = await resp.text()
                        logger.error(f"❌ Failed to create Local channel: {resp.status} - {error_text}")
                        self.test_results["errors"].append(f"Failed to create Local channel: {resp.status} - {error_text}")
                        return None
                
        except Exception as e:
            logger.error(f"❌ Channel creation test failed: {e}")
            self.test_results["errors"].append(f"Channel creation test failed: {e}")
            return None
    
    async def test_bridge_creation(self):
        """Test bridge creation and management"""
        logger.info("🔍 Testing Bridge Creation...")
        try:
            async with aiohttp.ClientSession() as session:
                # Test 1: Create a bridge
                bridge_data = {
                    "type": "mixing"
                }
                
                async with session.post(
                    f"{self.ari_base}/bridges",
                    auth=self.ari_auth,
                    json=bridge_data
                ) as resp:
                    if resp.status in [200, 201]:
                        bridge_info = await resp.json()
                        bridge_id = bridge_info["id"]
                        logger.info(f"✅ Bridge created: {bridge_id}")
                        self.test_results["bridge_creation"] = True
                        return bridge_id
                    else:
                        error_text = await resp.text()
                        logger.error(f"❌ Failed to create bridge: {resp.status} - {error_text}")
                        self.test_results["errors"].append(f"Failed to create bridge: {resp.status} - {error_text}")
                        return None
                
        except Exception as e:
            logger.error(f"❌ Bridge creation test failed: {e}")
            self.test_results["errors"].append(f"Bridge creation test failed: {e}")
            return None
    
    async def test_audiosocket_connection(self):
        """Test AudioSocket connection capabilities"""
        logger.info("🔍 Testing AudioSocket Connection...")
        try:
            # Check if AudioSocket server is running
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(('127.0.0.1', 8090))
            sock.close()
            
            if result == 0:
                logger.info("✅ AudioSocket server is listening on port 8090")
                self.test_results["audiosocket_connection"] = True
                return True
            else:
                logger.error("❌ AudioSocket server is not listening on port 8090")
                self.test_results["errors"].append("AudioSocket server not listening on port 8090")
                return False
                
        except Exception as e:
            logger.error(f"❌ AudioSocket connection test failed: {e}")
            self.test_results["errors"].append(f"AudioSocket connection test failed: {e}")
            return False
    
    async def test_audio_playback(self):
        """Test audio playback capabilities"""
        logger.info("🔍 Testing Audio Playback...")
        try:
            async with aiohttp.ClientSession() as session:
                # Test 1: Create a test channel
                channel_data = {
                    "endpoint": "Local/s@from-ai-agent",
                    "app": self.app_name,
                    "appArgs": "test"
                }
                
                async with session.post(
                    f"{self.ari_base}/channels",
                    auth=self.ari_auth,
                    json=channel_data
                ) as resp:
                    if resp.status in [200, 201]:
                        channel_info = await resp.json()
                        channel_id = channel_info["id"]
                        logger.info(f"✅ Test channel created: {channel_id}")
                        
                        # Test 2: Answer the channel
                        async with session.post(
                            f"{self.ari_base}/channels/{channel_id}/answer",
                            auth=self.ari_auth
                        ) as resp:
                            if resp.status == 204:
                                logger.info("✅ Channel answered")
                                
                                # Test 3: Play a test tone
                                async with session.post(
                                    f"{self.ari_base}/channels/{channel_id}/play",
                                    auth=self.ari_auth,
                                    json={"media": "tone:440;1000"}
                                ) as resp:
                                    if resp.status in [200, 201]:
                                        logger.info("✅ Audio playback initiated")
                                        self.test_results["audio_playback"] = True
                                        
                                        # Wait for playback to complete
                                        await asyncio.sleep(2)
                                        
                                        # Clean up
                                        async with session.delete(
                                            f"{self.ari_base}/channels/{channel_id}",
                                            auth=self.ari_auth
                                        ) as resp:
                                            logger.info("✅ Test channel cleaned up")
                                        
                                        return True
                                    else:
                                        error_text = await resp.text()
                                        logger.error(f"❌ Audio playback failed: {resp.status} - {error_text}")
                                        self.test_results["errors"].append(f"Audio playback failed: {resp.status} - {error_text}")
                                        return False
                            else:
                                logger.error(f"❌ Failed to answer channel: {resp.status}")
                                self.test_results["errors"].append(f"Failed to answer channel: {resp.status}")
                                return False
                    else:
                        error_text = await resp.text()
                        logger.error(f"❌ Failed to create test channel: {resp.status} - {error_text}")
                        self.test_results["errors"].append(f"Failed to create test channel: {resp.status} - {error_text}")
                        return False
                
        except Exception as e:
            logger.error(f"❌ Audio playback test failed: {e}")
            self.test_results["errors"].append(f"Audio playback test failed: {e}")
            return False
    
    async def test_ai_provider_connectivity(self):
        """Test AI provider connectivity"""
        logger.info("🔍 Testing AI Provider Connectivity...")
        try:
            # Test Local AI Server connection
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(('127.0.0.1', 8765))
            sock.close()
            
            if result == 0:
                logger.info("✅ Local AI Server is listening on port 8765")
                return True
            else:
                logger.error("❌ Local AI Server is not listening on port 8765")
                self.test_results["errors"].append("Local AI Server not listening on port 8765")
                return False
                
        except Exception as e:
            logger.error(f"❌ AI provider connectivity test failed: {e}")
            self.test_results["errors"].append(f"AI provider connectivity test failed: {e}")
            return False
    
    async def monitor_call_events(self, duration=60):
        """Monitor call events during test call"""
        logger.info(f"🔍 Monitoring call events for {duration} seconds...")
        try:
            async with aiohttp.ClientSession() as session:
                # Get WebSocket URL for events
                ws_url = f"ws://127.0.0.1:8088/ari/events?api_key=AIAgent:AiAgent%2B2025%3F&app={self.app_name}&subscribeAll=true"
                
                logger.info(f"Connecting to WebSocket: {ws_url}")
                
                # This would require a WebSocket client, for now we'll use HTTP polling
                start_time = time.time()
                events = []
                
                while time.time() - start_time < duration:
                    async with session.get(
                        f"{self.ari_base}/events",
                        auth=self.ari_auth,
                        params={"app": self.app_name}
                    ) as resp:
                        if resp.status == 200:
                            event_data = await resp.json()
                            if event_data:
                                events.extend(event_data)
                                logger.info(f"📡 Received {len(event_data)} events")
                        else:
                            logger.warning(f"⚠️ Failed to get events: {resp.status}")
                    
                    await asyncio.sleep(1)
                
                logger.info(f"✅ Collected {len(events)} events during monitoring")
                return events
                
        except Exception as e:
            logger.error(f"❌ Call event monitoring failed: {e}")
            self.test_results["errors"].append(f"Call event monitoring failed: {e}")
            return []
    
    async def analyze_container_logs(self):
        """Analyze container logs for issues"""
        logger.info("🔍 Analyzing Container Logs...")
        try:
            # Get recent logs from ai-engine
            result = subprocess.run([
                "docker", "logs", "--tail", "100", "ai_engine"
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                logs = result.stdout
                logger.info(f"✅ Retrieved {len(logs)} characters of ai-engine logs")
                
                # Analyze logs for common issues
                issues = []
                if "Failed to originate Local channel" in logs:
                    issues.append("Local channel origination failure")
                if "Channel not in Stasis application" in logs:
                    issues.append("Stasis application channel issue")
                if "AudioSocket connection accepted" in logs:
                    issues.append("AudioSocket connection working")
                if "Failed to add channel to bridge" in logs:
                    issues.append("Bridge add channel failure")
                if "Received non-audio AudioSocket message" in logs:
                    issues.append("AudioSocket protocol issue")
                
                if issues:
                    logger.info(f"🔍 Found issues in logs: {issues}")
                    self.test_results["warnings"].extend(issues)
                else:
                    logger.info("✅ No major issues found in logs")
                
                return logs
            else:
                logger.error(f"❌ Failed to get container logs: {result.stderr}")
                self.test_results["errors"].append(f"Failed to get container logs: {result.stderr}")
                return ""
                
        except Exception as e:
            logger.error(f"❌ Container log analysis failed: {e}")
            self.test_results["errors"].append(f"Container log analysis failed: {e}")
            return ""
    
    async def generate_recommendations(self):
        """Generate recommendations based on test results"""
        logger.info("🔍 Generating Recommendations...")
        
        recommendations = []
        
        # ARI Connectivity
        if not self.test_results["ari_connectivity"]:
            recommendations.append("Fix ARI connectivity - check credentials and network")
        
        # Channel Creation
        if not self.test_results["channel_creation"]:
            recommendations.append("Fix channel creation - check dialplan and ARI permissions")
        
        # Bridge Creation
        if not self.test_results["bridge_creation"]:
            recommendations.append("Fix bridge creation - check ARI permissions")
        
        # AudioSocket Connection
        if not self.test_results["audiosocket_connection"]:
            recommendations.append("Fix AudioSocket server - check if it's running and listening on port 8090")
        
        # Audio Playback
        if not self.test_results["audio_playback"]:
            recommendations.append("Fix audio playback - check channel state and media permissions")
        
        # AI Provider
        if not self.test_results["stt_processing"]:
            recommendations.append("Fix STT processing - check Local AI Server connectivity")
        
        # Architecture Issues
        if "Local channel origination failure" in self.test_results["warnings"]:
            recommendations.append("CRITICAL: Local Channel Bridge pattern is fundamentally broken - consider direct AudioSocket approach")
        
        if "Stasis application channel issue" in self.test_results["warnings"]:
            recommendations.append("CRITICAL: Local channels cannot be added to Stasis bridges - architectural limitation")
        
        if "AudioSocket protocol issue" in self.test_results["warnings"]:
            recommendations.append("Fix AudioSocket protocol - check TLV frame format and UUID handling")
        
        self.test_results["recommendations"] = recommendations
        return recommendations
    
    async def run_comprehensive_test(self):
        """Run comprehensive test suite"""
        logger.info("🚀 Starting Comprehensive Test Analysis...")
        start_time = time.time()
        
        try:
            # Test 1: ARI Connectivity
            await self.test_ari_connectivity()
            
            # Test 2: Channel Creation
            channel_id = await self.test_channel_creation()
            
            # Test 3: Bridge Creation
            bridge_id = await self.test_bridge_creation()
            
            # Test 4: AudioSocket Connection
            await self.test_audiosocket_connection()
            
            # Test 5: Audio Playback
            await self.test_audio_playback()
            
            # Test 6: AI Provider Connectivity
            await self.test_ai_provider_connectivity()
            
            # Test 7: Monitor call events (wait for user to make test call)
            logger.info("⏳ Waiting for test call... Please make a test call now!")
            events = await self.monitor_call_events(60)
            
            # Test 8: Analyze container logs
            logs = await self.analyze_container_logs()
            
            # Test 9: Generate recommendations
            recommendations = await self.generate_recommendations()
            
            # Calculate test duration
            self.test_results["test_duration"] = time.time() - start_time
            
            # Generate final report
            await self.generate_final_report()
            
        except Exception as e:
            logger.error(f"❌ Comprehensive test failed: {e}")
            self.test_results["errors"].append(f"Comprehensive test failed: {e}")
    
    async def generate_final_report(self):
        """Generate final comprehensive report"""
        logger.info("📊 Generating Final Report...")
        
        report = {
            "test_summary": {
                "timestamp": self.test_results["timestamp"],
                "duration": f"{self.test_results['test_duration']:.2f} seconds",
                "total_errors": len(self.test_results["errors"]),
                "total_warnings": len(self.test_results["warnings"]),
                "total_recommendations": len(self.test_results["recommendations"])
            },
            "test_results": self.test_results,
            "critical_findings": [],
            "next_steps": []
        }
        
        # Identify critical findings
        if "Local channel origination failure" in self.test_results["warnings"]:
            report["critical_findings"].append("Local Channel Bridge pattern is fundamentally broken")
        
        if "Stasis application channel issue" in self.test_results["warnings"]:
            report["critical_findings"].append("Local channels cannot be added to Stasis bridges")
        
        if "AudioSocket protocol issue" in self.test_results["warnings"]:
            report["critical_findings"].append("AudioSocket protocol has issues")
        
        # Determine next steps
        if report["critical_findings"]:
            report["next_steps"].append("Abandon Local Channel Bridge pattern")
            report["next_steps"].append("Implement direct AudioSocket approach (like AVR project)")
            report["next_steps"].append("Modify dialplan to use Dial(AudioSocket/...) directly")
        else:
            report["next_steps"].append("Fix identified issues and retest")
            report["next_steps"].append("Implement recommended solutions")
        
        # Save report to file
        report_file = f"/tmp/comprehensive_test_report_{int(time.time())}.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"📊 Final report saved to: {report_file}")
        
        # Print summary
        logger.info("=" * 80)
        logger.info("📊 COMPREHENSIVE TEST ANALYSIS SUMMARY")
        logger.info("=" * 80)
        logger.info(f"⏱️  Test Duration: {report['test_summary']['duration']}")
        logger.info(f"❌ Total Errors: {report['test_summary']['total_errors']}")
        logger.info(f"⚠️  Total Warnings: {report['test_summary']['total_warnings']}")
        logger.info(f"💡 Total Recommendations: {report['test_summary']['total_recommendations']}")
        logger.info("")
        
        if report["critical_findings"]:
            logger.info("🚨 CRITICAL FINDINGS:")
            for finding in report["critical_findings"]:
                logger.info(f"   • {finding}")
            logger.info("")
        
        if report["next_steps"]:
            logger.info("🎯 RECOMMENDED NEXT STEPS:")
            for step in report["next_steps"]:
                logger.info(f"   • {step}")
            logger.info("")
        
        logger.info("=" * 80)
        
        return report

async def main():
    test = ComprehensiveTestAnalysis()
    await test.run_comprehensive_test()

if __name__ == "__main__":
    asyncio.run(main())
