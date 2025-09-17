#!/usr/bin/env python3
"""
Enhanced Model Manager for Asterisk AI Voice Agent
Analyzes system capabilities and manages model downloads/selection
"""

import os
import sys
import json
import psutil
import platform
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple, Optional

class SystemAnalyzer:
    """Analyzes system specifications and recommends optimal models"""
    
    def __init__(self):
        self.specs = self._analyze_system()
        self.tier = self._determine_tier()
    
    def _analyze_system(self) -> Dict:
        """Analyze system specifications"""
        return {
            'cpu_cores': psutil.cpu_count(logical=False),
            'logical_cores': psutil.cpu_count(logical=True),
            'total_ram_gb': round(psutil.virtual_memory().total / (1024**3), 1),
            'available_ram_gb': round(psutil.virtual_memory().available / (1024**3), 1),
            'total_disk_gb': round(psutil.disk_usage('/').total / (1024**3), 1),
            'free_disk_gb': round(psutil.disk_usage('/').free / (1024**3), 1),
            'architecture': platform.machine(),
            'is_docker': os.path.exists('/.dockerenv'),
            'python_version': sys.version_info
        }
    
    def _determine_tier(self) -> str:
        """Determine system tier based on specifications"""
        ram_gb = self.specs['total_ram_gb']
        cpu_cores = self.specs['cpu_cores']
        
        if ram_gb >= 32 and cpu_cores >= 8:
            return 'HEAVY'
        elif ram_gb >= 16 and cpu_cores >= 4:
            return 'MEDIUM'
        else:
            return 'LIGHT'
    
    def get_model_recommendations(self) -> Dict:
        """Get model recommendations based on system tier - MVP Focus on uLaw 8kHz compatibility"""
        recommendations = {
            'HEAVY': {
                'stt': {
                    'model': 'vosk-model-en-us-0.22',
                    'size_gb': 1.8,
                    'quality': 'High',
                    'native_sample_rate': 16000,
                    'input_sample_rate': 8000,
                    'resampling_required': True,
                    'description': 'Large Vosk model with high accuracy (8kHz→16kHz resampling)'
                },
                'tts': {
                    'model': 'en_US-lessac-medium',
                    'size_gb': 0.06,
                    'quality': 'High',
                    'native_sample_rate': 22050,
                    'target_sample_rate': 8000,
                    'resampling_required': True,
                    'description': 'High quality neural TTS (22kHz→8kHz uLaw conversion)'
                }
            },
            'MEDIUM': {
                'stt': {
                    'model': 'vosk-model-small-en-us-0.15',
                    'size_gb': 0.04,
                    'quality': 'Medium',
                    'native_sample_rate': 16000,
                    'input_sample_rate': 8000,
                    'resampling_required': True,
                    'description': 'Balanced Vosk model (8kHz→16kHz resampling)'
                },
                'tts': {
                    'model': 'en_US-lessac-medium',
                    'size_gb': 0.06,
                    'quality': 'High',
                    'native_sample_rate': 22050,
                    'target_sample_rate': 8000,
                    'resampling_required': True,
                    'description': 'High quality neural TTS (22kHz→8kHz uLaw conversion)'
                }
            },
            'LIGHT': {
                'stt': {
                    'model': 'vosk-model-small-en-us-0.15',
                    'size_gb': 0.04,
                    'quality': 'Medium',
                    'native_sample_rate': 16000,
                    'input_sample_rate': 8000,
                    'resampling_required': True,
                    'description': 'Lightweight Vosk model (8kHz→16kHz resampling)'
                },
                'tts': {
                    'model': 'en_US-lessac-medium',
                    'size_gb': 0.06,
                    'quality': 'High',
                    'native_sample_rate': 22050,
                    'target_sample_rate': 8000,
                    'resampling_required': True,
                    'description': 'High quality neural TTS (22kHz→8kHz uLaw conversion)'
                }
            }
        }
        
        return recommendations[self.tier]
    
    def get_performance_estimates(self) -> Dict:
        """Get performance estimates based on system specs"""
        ram_gb = self.specs['total_ram_gb']
        cpu_cores = self.specs['cpu_cores']
        
        return {
            'max_concurrent_calls': min(ram_gb // 2, cpu_cores * 2),
            'recommended_audio_buffer_size': 1024 if self.tier == 'HEAVY' else 512,
            'llm_context_length': 4096 if self.tier == 'HEAVY' else 2048,
            'stt_chunk_size': 3200 if self.tier == 'HEAVY' else 1600,
            'tts_chunk_size': 1024 if self.tier == 'HEAVY' else 512
        }

class ModelManager:
    """Manages model downloads and configuration"""
    
    def __init__(self, models_dir: str = "models"):
        self.models_dir = Path(models_dir)
        self.analyzer = SystemAnalyzer()
        self.config_file = Path("model_config.json")
    
    def check_existing_models(self) -> Dict[str, bool]:
        """Check which models are already downloaded"""
        stt_dir = self.models_dir / "stt"
        llm_dir = self.models_dir / "llm"
        tts_dir = self.models_dir / "tts"
        
        recommendations = self.analyzer.get_model_recommendations()
        
        return {
            'stt': (stt_dir / recommendations['stt']['model']).exists(),
            'llm': (llm_dir / recommendations['llm']['model']).exists(),
            'tts': (tts_dir / f"{recommendations['tts']['model']}.onnx").exists()
        }
    
    def generate_config(self) -> Dict:
        """Generate model configuration based on system analysis"""
        recommendations = self.analyzer.get_model_recommendations()
        performance = self.analyzer.get_performance_estimates()
        existing = self.check_existing_models()
        
        config = {
            'system_tier': self.analyzer.tier,
            'system_specs': self.analyzer.specs,
            'models': {
                'stt': {
                    'name': recommendations['stt']['model'],
                    'path': str(self.models_dir / "stt" / recommendations['stt']['model']),
                    'type': 'vosk',
                    'sample_rate': recommendations['stt']['sample_rate'],
                    'format': 'pcm16',
                    'downloaded': existing['stt'],
                    'size_gb': recommendations['stt']['size_gb']
                },
                'llm': {
                    'name': recommendations['llm']['model'],
                    'path': str(self.models_dir / "llm" / recommendations['llm']['model']),
                    'type': 'llama-cpp',
                    'format': 'gguf',
                    'downloaded': existing['llm'],
                    'size_gb': recommendations['llm']['size_gb']
                },
                'tts': {
                    'name': recommendations['tts']['model'],
                    'path': str(self.models_dir / "tts" / f"{recommendations['tts']['model']}.onnx"),
                    'type': 'piper',
                    'sample_rate': recommendations['tts']['sample_rate'],
                    'format': 'wav',
                    'downloaded': existing['tts'],
                    'size_gb': recommendations['tts']['size_gb']
                }
            },
            'performance': performance,
            'recommendations': {
                'total_size_gb': sum(rec['size_gb'] for rec in recommendations.values()),
                'download_needed': not all(existing.values()),
                'missing_models': [k for k, v in existing.items() if not v]
            }
        }
        
        return config
    
    def save_config(self, config: Dict) -> None:
        """Save configuration to file"""
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=2)
        print(f"Configuration saved to {self.config_file}")
    
    def print_system_analysis(self) -> None:
        """Print detailed system analysis"""
        print("=== SYSTEM ANALYSIS ===")
        print(f"System Tier: {self.analyzer.tier}")
        print(f"CPU Cores: {self.analyzer.specs['cpu_cores']} physical, {self.analyzer.specs['logical_cores']} logical")
        print(f"Total RAM: {self.analyzer.specs['total_ram_gb']} GB")
        print(f"Available RAM: {self.analyzer.specs['available_ram_gb']} GB")
        print(f"Free Disk: {self.analyzer.specs['free_disk_gb']} GB")
        print(f"Architecture: {self.analyzer.specs['architecture']}")
        print(f"Environment: {'Docker' if self.analyzer.specs['is_docker'] else 'Host'}")
        print()
    
    def print_model_recommendations(self) -> None:
        """Print model recommendations - MVP Focus on uLaw 8kHz compatibility"""
        recommendations = self.analyzer.get_model_recommendations()
        performance = self.analyzer.get_performance_estimates()
        existing = self.check_existing_models()
        
        print("=== MVP MODEL RECOMMENDATIONS (uLaw 8kHz Compatible) ===")
        print("Audio Pipeline: AudioSocket (8kHz) → STT (resampled to 16kHz) → TTS (resampled to 8kHz) → ARI (uLaw 8kHz)")
        print()
        
        for model_type, model_info in recommendations.items():
            status = "✓ Downloaded" if existing[model_type] else "⚠️  Not Downloaded"
            print(f"{model_type.upper()}:")
            print(f"  Model: {model_info['model']}")
            print(f"  Size: {model_info['size_gb']} GB")
            print(f"  Quality: {model_info['quality']}")
            print(f"  Native Rate: {model_info['native_sample_rate']}Hz")
            print(f"  Target Rate: {model_info['input_sample_rate'] if model_type == 'stt' else model_info['target_sample_rate']}Hz")
            print(f"  Resampling: {'Required' if model_info['resampling_required'] else 'Not Required'}")
            print(f"  Description: {model_info['description']}")
            print(f"  Status: {status}")
            print()
        
        print("=== AUDIO CONVERSION REQUIREMENTS ===")
        print("STT Input:  AudioSocket PCM16LE 8kHz → Vosk PCM16 16kHz (sox resample)")
        print("TTS Output: Piper WAV 22kHz → ARI uLaw 8kHz (sox convert)")
        print("Tools Required: sox (for resampling and format conversion)")
        print()
        
        print("=== PERFORMANCE ESTIMATES ===")
        print(f"Max Concurrent Calls: {performance['max_concurrent_calls']}")
        print(f"Audio Buffer Size: {performance['recommended_audio_buffer_size']}")
        print(f"STT Chunk Size: {performance['stt_chunk_size']}")
        print(f"TTS Chunk Size: {performance['tts_chunk_size']}")
        print()

def main():
    """Main function"""
    if len(sys.argv) > 1 and sys.argv[1] == 'analyze':
        manager = ModelManager()
        manager.print_system_analysis()
        manager.print_model_recommendations()
        
        config = manager.generate_config()
        manager.save_config(config)
        
        if config['recommendations']['download_needed']:
            print("=== NEXT STEPS ===")
            print("Run the download script to get missing models:")
            print("  ./scripts/download_models.sh")
            print()
            print("Missing models:")
            for model in config['recommendations']['missing_models']:
                print(f"  - {model.upper()}")
        else:
            print("✓ All recommended models are already downloaded!")
    
    else:
        print("Usage: python3 model_manager.py analyze")
        print("This will analyze your system and recommend optimal models.")

if __name__ == "__main__":
    main()
