#!/usr/bin/env python3

import os
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

# Suppress deprecation warning for google.generativeai
import warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="google.generativeai")

import google.generativeai as genai
from google.generativeai.types import GenerationConfig, HarmCategory, HarmBlockThreshold


class RateLimiter:
    """
    Sliding window rate limiter for API calls
    
    Prevents exceeding API quotas by tracking call timestamps and enforcing
    a maximum calls per time window limit.
    """
    
    def __init__(self, max_calls: int = 15, time_window: int = 60):
        """
        Initialize rate limiter
        
        Args:
            max_calls: Maximum calls allowed in time window
            time_window: Time window in seconds (default 60 = 1 minute)
        """
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls = []  # List of call timestamps
    
    def wait_if_needed(self):
        """
        Check if rate limit would be exceeded and wait if necessary
        
        Removes expired timestamps and calculates wait time based on
        oldest call in the current window.
        """
        now = datetime.now()
        
        # Remove calls outside time window
        self.calls = [
            call_time for call_time in self.calls
            if (now - call_time).total_seconds() < self.time_window
        ]
        
        # Check if we're at limit
        if len(self.calls) >= self.max_calls:
            # Wait until oldest call expires
            oldest_call = min(self.calls)
            wait_until = oldest_call + timedelta(seconds=self.time_window)
            wait_seconds = (wait_until - now).total_seconds()
            
            if wait_seconds > 0:
                print(f"⏳ Rate limit: waiting {wait_seconds:.1f}s...")
                time.sleep(wait_seconds)
    
    def record_call(self):
        """
        Record a successful API call timestamp
        
        IMPORTANT: Only call this AFTER successful API response,
        not before the call or on retries. This prevents counting
        retries as separate API calls.
        """
        self.calls.append(datetime.now())


class LLMClient:
    """
    Unified interface for LLM providers (Gemini primary, Claude fallback)
    
    Handles:
    - Rate limiting (15 RPM for Gemini free tier)
    - Retry logic with exponential backoff
    - Safety filter management
    - Token tracking and cost estimation
    - JSON output formatting
    """
    
    def __init__(self, provider: Optional[str] = None, verbose: bool = False):
        """
        Initialize LLM client
        
        Args:
            provider: "gemini" or "anthropic" (defaults to gemini)
            verbose: Enable detailed logging
        """
        self.provider = provider or "gemini"
        self.verbose = verbose
        self.rate_limiter = RateLimiter(max_calls=15, time_window=60)
        
        # Usage tracking
        self.total_tokens = 0
        self.total_cost = 0.0
        self.api_calls = 0
        
        # Initialize provider
        if self.provider == "gemini":
            genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
            # Use gemini-2.5-flash (current stable model as of Feb 2026)
            self.model = genai.GenerativeModel("gemini-2.5-flash")
            if self.verbose:
                print("✅ Initialized Gemini: gemini-2.5-flash")
        else:
            self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            if self.verbose:
                print("✅ Initialized Anthropic: claude-sonnet-4")
    
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        response_format: Optional[str] = None,
        retry_count: int = 3
    ) -> str:
        """
        Generate text response from LLM
        
        Args:
            prompt: User prompt/question
            system_prompt: System instructions (optional)
            temperature: Randomness (0.0-1.0)
            max_tokens: Maximum tokens to generate
            response_format: "json" to force JSON output
            retry_count: Number of retries on failure
        
        Returns:
            Generated text response
        
        Raises:
            Exception: If generation fails after all retries
        """
        # Retry logic with exponential backoff
        for attempt in range(retry_count):
            # Rate limiting - only on first attempt (not retries)
            if attempt == 0:
                self.rate_limiter.wait_if_needed()
            
            try:
                # Call provider-specific generation
                if self.provider == "gemini":
                    result = self._generate_gemini(
                        prompt, system_prompt, temperature, max_tokens, response_format
                    )
                else:
                    result = self._generate_anthropic(
                        prompt, system_prompt, temperature, max_tokens, response_format
                    )
                
                # Record successful call
                self.rate_limiter.record_call()
                self.api_calls += 1
                return result
                    
            except Exception as e:
                error_msg = str(e)
                error_type = type(e).__name__
                
                if self.verbose:
                    print(f"[DEBUG] Error: {error_type}: {error_msg[:100]}")
                
                # Check if it's a safety filter block (don't retry these)
                if "safety filter" in error_msg.lower() or "blocked" in error_msg.lower():
                    # For safety blocks, try Claude fallback if available
                    if self.provider == "gemini" and attempt == 0:
                        if self.verbose:
                            print("⚠️  Gemini blocked by safety filters, trying Claude fallback...")
                        try:
                            import anthropic
                            claude = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
                            result = self._generate_with_claude_fallback(
                                claude, prompt, system_prompt, temperature, max_tokens, response_format
                            )
                            self.api_calls += 1
                            return result
                        except Exception as fallback_error:
                            raise Exception(f"Both Gemini and Claude failed: {error_msg}, {str(fallback_error)}")
                    else:
                        raise Exception(f"Content blocked by safety filters: {error_msg}")
                
                # Check if it's a rate limit error (use specific patterns)
                if "429" in error_msg or "rate limit" in error_msg.lower() or "quota" in error_msg.lower() or "resource_exhausted" in error_msg.lower():
                    if attempt < retry_count - 1:
                        wait_time = 2 ** (attempt + 1)  # 2s, 4s, 8s
                        print(f"⏳ Rate limited by API, waiting {wait_time}s (attempt {attempt + 1}/{retry_count})")
                        time.sleep(wait_time)
                        continue
                    else:
                        raise Exception(f"Rate limit exceeded after {retry_count} attempts")
                
                # Other transient errors - retry with backoff
                if attempt < retry_count - 1:
                    wait_time = 2 ** attempt  # 1s, 2s, 4s
                    print(f"⚠️  Retrying in {wait_time}s... (attempt {attempt + 1}/{retry_count})")
                    time.sleep(wait_time)
                    continue
                else:
                    # Final attempt failed
                    raise Exception(f"LLM generation failed after {retry_count} attempts: {error_msg}")
        
        raise Exception("LLM generation failed: max retries exceeded")
    
    def _generate_gemini(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int,
        response_format: Optional[str]
    ) -> str:
        """Generate response using Gemini"""
        
        # Combine system prompt and user prompt
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"
        
        # If JSON format requested, add instruction
        if response_format == "json":
            full_prompt += "\n\nIMPORTANT: Respond with valid JSON only, no markdown, no other text."
        
        # Generation config
        generation_config = GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        
        # Safety settings - BLOCK_NONE for technical content
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }
        
        # Call Gemini API
        response = self.model.generate_content(
            full_prompt,
            generation_config=generation_config,
            safety_settings=safety_settings
        )
        
        # Check if response was blocked by safety filters
        if hasattr(response, 'candidates') and response.candidates:
            finish_reason = response.candidates[0].finish_reason
            # Finish reasons: 0=UNSPECIFIED, 1=STOP (normal), 2=SAFETY, 3=RECITATION, 4=OTHER, 5=MAX_TOKENS
            if finish_reason == 2:  # SAFETY
                raise Exception("Response blocked by safety filters")
            elif finish_reason == 3:  # RECITATION
                raise Exception("Response blocked due to recitation/copyright concerns")
            elif finish_reason not in [0, 1, 5]:  # Not UNSPECIFIED, STOP, or MAX_TOKENS
                raise Exception(f"Response generation incomplete (finish_reason: {finish_reason})")
        
        # Track token usage
        try:
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                tokens = response.usage_metadata.total_token_count
                self.total_tokens += tokens
                # Gemini 2.0 Flash pricing: ~$0.075 per 1M input tokens, $0.30 per 1M output
                # Using average of $0.15 per 1M tokens
                self.total_cost += (tokens / 1_000_000) * 0.15
                
                if self.verbose:
                    print(f"📊 Tokens used: {tokens}")
        except Exception as e:
            if self.verbose:
                print(f"⚠️  Could not track token usage: {e}")
        
        # Extract text safely
        try:
            return response.text
        except (ValueError, AttributeError) as e:
            # Fallback if .text accessor fails
            if hasattr(response, 'candidates') and response.candidates:
                if response.candidates[0].content.parts:
                    return response.candidates[0].content.parts[0].text
            raise Exception(f"Could not extract response text: {e}")
    
    def _generate_with_claude_fallback(
        self,
        claude_client,
        prompt: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int,
        response_format: Optional[str]
    ) -> str:
        """Generate response using Claude as fallback"""
        
        # Build messages
        messages = [{"role": "user", "content": prompt}]
        
        # Add JSON instruction if needed
        if response_format == "json":
            messages[0]["content"] += "\n\nIMPORTANT: Respond with valid JSON only, no markdown, no other text."
        
        # Call Claude
        response = claude_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt or "You are a helpful assistant.",
            messages=messages
        )
        
        # Track usage
        if hasattr(response, 'usage'):
            tokens = response.usage.input_tokens + response.usage.output_tokens
            self.total_tokens += tokens
            # Claude pricing: ~$3 per 1M input, $15 per 1M output (avg $9)
            self.total_cost += (tokens / 1_000_000) * 9.0
            
            if self.verbose:
                print(f"📊 Tokens used (Claude): {tokens}")
        
        return response.content[0].text
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """
        Get usage statistics
        
        Returns:
            Dict with total_tokens, estimated_cost_usd, api_calls
        """
        return {
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": self.total_cost,
            "api_calls": self.api_calls,
            "provider": self.provider
        }


################################################################################
# TEST SUITE
################################################################################

if __name__ == "__main__":
    print("🧪 LLM Client Test Suite\n")
    
    # Test 1: Basic generation
    print("1️⃣  Test: Basic generation")
    try:
        client = LLMClient(verbose=True)
        response = client.generate("What is 2+2? Answer with just the number.")
        print(f"✅ Response: {response}\n")
    except Exception as e:
        print(f"❌ Test failed: {e}\n")
    
    # Test 2: JSON output
    print("2️⃣  Test: JSON output")
    try:
        response = client.generate(
            prompt="Generate a simple JSON with 'status': 'ok' and 'message': 'test'",
            response_format="json"
        )
        print(f"✅ Response: {response}\n")
        
        import json
        parsed = json.loads(response)
        print(f"✅ Valid JSON! Keys: {list(parsed.keys())}\n")
    except Exception as e:
        print(f"❌ Test failed: {e}\n")
    
    # Test 3: System prompt
    print("3️⃣  Test: System prompt")
    try:
        response = client.generate(
            prompt="What's the capital of France?",
            system_prompt="You are a geography expert. Answer concisely.",
            max_tokens=50
        )
        print(f"✅ Response: {response}\n")
    except Exception as e:
        print(f"❌ Test failed: {e}\n")
    
    # Test 4: Usage stats
    print("4️⃣  Test: Usage statistics")
    stats = client.get_usage_stats()
    print(f"📊 Total API Calls: {stats['api_calls']}")
    print(f"📊 Total Tokens: {stats['total_tokens']:,}")
    print(f"💰 Estimated Cost: ${stats['estimated_cost_usd']:.6f}")
    print(f"🏷️  Provider: {stats['provider']}\n")
    
    print("✅ All tests completed!")
