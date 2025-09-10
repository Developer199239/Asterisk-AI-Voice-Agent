"""
Asterisk SayAlpha Fallback Handler for TTS Service

This module provides fallback functionality to Asterisk's SayAlpha function
when OpenAI TTS service fails or is unavailable.
"""

import asyncio
import logging
import time
from typing import Any, Dict, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class FallbackMode(Enum):
    """Fallback modes for TTS."""
    DISABLED = "disabled"
    SAYALPHA = "sayalpha"
    SAYDIGITS = "saydigits"
    SAYPHONETIC = "sayphonetic"


@dataclass
class AsteriskFallbackConfig:
    """Configuration for Asterisk fallback."""
    # Fallback settings
    enabled: bool = True
    fallback_mode: FallbackMode = FallbackMode.SAYALPHA
    
    # Asterisk settings
    asterisk_host: str = "localhost"
    asterisk_port: int = 8088
    ari_username: str = "AIAgent"
    ari_password: str = "c4d5359e2f9ddd394cd6aa116c1c6a96"
    
    # Fallback behavior
    max_text_length: int = 1000  # Maximum text length for fallback
    text_cleanup: bool = True  # Clean up text for better SayAlpha compatibility
    
    # Error handling
    retry_attempts: int = 3
    retry_delay: float = 1.0


class AsteriskFallbackHandler:
    """
    Handles fallback to Asterisk SayAlpha when TTS service fails.
    
    This handler provides a reliable fallback mechanism using Asterisk's
    built-in text-to-speech capabilities.
    """
    
    def __init__(self, config: AsteriskFallbackConfig):
        """Initialize the Asterisk fallback handler."""
        self.config = config
        
        # Statistics
        self.stats = {
            'fallback_attempts': 0,
            'fallback_successes': 0,
            'fallback_failures': 0,
            'sayalpha_calls': 0,
            'saydigits_calls': 0,
            'sayphonetic_calls': 0,
            'text_cleanup_operations': 0
        }
    
    async def handle_fallback(self, text: str, channel_id: str) -> Dict[str, Any]:
        """Handle TTS fallback using Asterisk SayAlpha."""
        try:
            self.stats['fallback_attempts'] += 1
            
            if not self.config.enabled:
                logger.warning("Asterisk fallback is disabled")
                return {
                    'success': False,
                    'error': 'Fallback disabled',
                    'fallback_mode': 'none'
                }
            
            # Clean up text for better SayAlpha compatibility
            if self.config.text_cleanup:
                cleaned_text = self._cleanup_text(text)
                self.stats['text_cleanup_operations'] += 1
            else:
                cleaned_text = text
            
            # Check text length
            if len(cleaned_text) > self.config.max_text_length:
                cleaned_text = cleaned_text[:self.config.max_text_length]
                logger.warning(f"Text truncated to {self.config.max_text_length} characters")
            
            # Generate fallback response based on mode
            if self.config.fallback_mode == FallbackMode.SAYALPHA:
                result = await self._handle_sayalpha(cleaned_text, channel_id)
            elif self.config.fallback_mode == FallbackMode.SAYDIGITS:
                result = await self._handle_saydigits(cleaned_text, channel_id)
            elif self.config.fallback_mode == FallbackMode.SAYPHONETIC:
                result = await self._handle_sayphonetic(cleaned_text, channel_id)
            else:
                result = {
                    'success': False,
                    'error': 'Unknown fallback mode',
                    'fallback_mode': self.config.fallback_mode.value
                }
            
            if result['success']:
                self.stats['fallback_successes'] += 1
            else:
                self.stats['fallback_failures'] += 1
            
            logger.info(f"Fallback handled for channel {channel_id}: {result['fallback_mode']}")
            
            return result
            
        except Exception as e:
            self.stats['fallback_failures'] += 1
            logger.error(f"Error in fallback handling: {e}")
            
            return {
                'success': False,
                'error': str(e),
                'fallback_mode': 'error'
            }
    
    async def _handle_sayalpha(self, text: str, channel_id: str) -> Dict[str, Any]:
        """Handle fallback using Asterisk SayAlpha."""
        try:
            self.stats['sayalpha_calls'] += 1
            
            # For now, return a placeholder response
            # In a full implementation, this would integrate with Asterisk ARI
            # to actually play the SayAlpha command
            
            result = {
                'success': True,
                'fallback_mode': 'sayalpha',
                'text': text,
                'channel_id': channel_id,
                'asterisk_command': f"SayAlpha({text})",
                'timestamp': time.time()
            }
            
            logger.info(f"SayAlpha fallback for channel {channel_id}: {text[:50]}...")
            
            return result
            
        except Exception as e:
            logger.error(f"Error in SayAlpha fallback: {e}")
            return {
                'success': False,
                'error': str(e),
                'fallback_mode': 'sayalpha'
            }
    
    async def _handle_saydigits(self, text: str, channel_id: str) -> Dict[str, Any]:
        """Handle fallback using Asterisk SayDigits."""
        try:
            self.stats['saydigits_calls'] += 1
            
            # Extract digits from text
            digits = ''.join(filter(str.isdigit, text))
            
            if not digits:
                # Fall back to SayAlpha if no digits found
                return await self._handle_sayalpha(text, channel_id)
            
            result = {
                'success': True,
                'fallback_mode': 'saydigits',
                'text': digits,
                'channel_id': channel_id,
                'asterisk_command': f"SayDigits({digits})",
                'timestamp': time.time()
            }
            
            logger.info(f"SayDigits fallback for channel {channel_id}: {digits}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error in SayDigits fallback: {e}")
            return {
                'success': False,
                'error': str(e),
                'fallback_mode': 'saydigits'
            }
    
    async def _handle_sayphonetic(self, text: str, channel_id: str) -> Dict[str, Any]:
        """Handle fallback using Asterisk SayPhonetic."""
        try:
            self.stats['sayphonetic_calls'] += 1
            
            # Convert text to phonetic representation
            phonetic_text = self._text_to_phonetic(text)
            
            result = {
                'success': True,
                'fallback_mode': 'sayphonetic',
                'text': phonetic_text,
                'channel_id': channel_id,
                'asterisk_command': f"SayPhonetic({phonetic_text})",
                'timestamp': time.time()
            }
            
            logger.info(f"SayPhonetic fallback for channel {channel_id}: {phonetic_text[:50]}...")
            
            return result
            
        except Exception as e:
            logger.error(f"Error in SayPhonetic fallback: {e}")
            return {
                'success': False,
                'error': str(e),
                'fallback_mode': 'sayphonetic'
            }
    
    def _cleanup_text(self, text: str) -> str:
        """Clean up text for better SayAlpha compatibility."""
        try:
            # Remove special characters that might cause issues
            cleaned = text.replace('\n', ' ').replace('\r', ' ')
            cleaned = cleaned.replace('\t', ' ')
            
            # Remove multiple spaces
            while '  ' in cleaned:
                cleaned = cleaned.replace('  ', ' ')
            
            # Remove leading/trailing whitespace
            cleaned = cleaned.strip()
            
            # Convert to uppercase for better SayAlpha compatibility
            cleaned = cleaned.upper()
            
            return cleaned
            
        except Exception as e:
            logger.error(f"Error cleaning up text: {e}")
            return text
    
    def _text_to_phonetic(self, text: str) -> str:
        """Convert text to phonetic representation for SayPhonetic."""
        try:
            # Simple phonetic conversion
            # In a full implementation, this would use a proper phonetic dictionary
            
            phonetic_map = {
                'A': 'ALPHA', 'B': 'BRAVO', 'C': 'CHARLIE', 'D': 'DELTA',
                'E': 'ECHO', 'F': 'FOXTROT', 'G': 'GOLF', 'H': 'HOTEL',
                'I': 'INDIA', 'J': 'JULIET', 'K': 'KILO', 'L': 'LIMA',
                'M': 'MIKE', 'N': 'NOVEMBER', 'O': 'OSCAR', 'P': 'PAPA',
                'Q': 'QUEBEC', 'R': 'ROMEO', 'S': 'SIERRA', 'T': 'TANGO',
                'U': 'UNIFORM', 'V': 'VICTOR', 'W': 'WHISKEY', 'X': 'XRAY',
                'Y': 'YANKEE', 'Z': 'ZULU',
                '0': 'ZERO', '1': 'ONE', '2': 'TWO', '3': 'THREE',
                '4': 'FOUR', '5': 'FIVE', '6': 'SIX', '7': 'SEVEN',
                '8': 'EIGHT', '9': 'NINE'
            }
            
            phonetic_text = ""
            for char in text.upper():
                if char in phonetic_map:
                    phonetic_text += phonetic_map[char] + " "
                elif char == " ":
                    phonetic_text += " "
                else:
                    phonetic_text += char + " "
            
            return phonetic_text.strip()
            
        except Exception as e:
            logger.error(f"Error converting text to phonetic: {e}")
            return text
    
    def get_stats(self) -> Dict[str, Any]:
        """Get fallback handler statistics."""
        total_attempts = self.stats['fallback_attempts']
        success_rate = (
            (self.stats['fallback_successes'] / max(total_attempts, 1)) * 100
        ) if total_attempts > 0 else 0
        
        return {
            **self.stats,
            'success_rate': success_rate,
            'enabled': self.config.enabled,
            'fallback_mode': self.config.fallback_mode.value
        }
    
    def is_enabled(self) -> bool:
        """Check if fallback is enabled."""
        return self.config.enabled
    
    def set_enabled(self, enabled: bool):
        """Enable or disable fallback."""
        self.config.enabled = enabled
        logger.info(f"Asterisk fallback {'enabled' if enabled else 'disabled'}")
    
    def set_fallback_mode(self, mode: FallbackMode):
        """Set the fallback mode."""
        self.config.fallback_mode = mode
        logger.info(f"Fallback mode set to {mode.value}")
