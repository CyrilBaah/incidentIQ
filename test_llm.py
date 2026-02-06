#!/usr/bin/env python3
"""Quick LLM client test with quota handling"""

from src.utils.llm_client import LLMClient
import os

print("🧪 Quick LLM Test\n")

# Initialize (try Claude if Gemini quota exceeded)
try:
    client = LLMClient(verbose=True)
    
    # Single quick test
    print("\n📝 Testing simple generation...")
    response = client.generate("What is 2+2? Answer with just the number.", max_tokens=20)
    print(f"✅ Response: {response}\n")
    
    # Check stats
    stats = client.get_usage_stats()
    print(f"📊 Stats:")
    print(f"   Calls: {stats['api_calls']}")
    print(f"   Tokens: {stats['total_tokens']}")
    print(f"   Cost: ${stats['estimated_cost_usd']:.6f}")
    
except Exception as e:
    error_msg = str(e)
    
    if "quota" in error_msg.lower() or "exceeded" in error_msg.lower():
        print(f"\n⚠️  Gemini quota exceeded. Trying Claude fallback...\n")
        
        # Try with Claude
        if os.getenv("ANTHROPIC_API_KEY"):
            try:
                client = LLMClient(provider="anthropic", verbose=True)
                response = client.generate("What is 2+2? Answer with just the number.", max_tokens=20)
                print(f"✅ Response (Claude): {response}\n")
                
                stats = client.get_usage_stats()
                print(f"📊 Stats:")
                print(f"   Calls: {stats['api_calls']}")
                print(f"   Tokens: {stats['total_tokens']}")
                print(f"   Cost: ${stats['estimated_cost_usd']:.6f}")
            except Exception as claude_error:
                print(f"❌ Claude also failed: {claude_error}")
        else:
            print("❌ No Anthropic API key found. Please wait for quota reset or add ANTHROPIC_API_KEY to .env")
            print("\n💡 Tip: Gemini free tier = 20 requests/day. Check usage at: https://ai.dev/rate-limit")
    else:
        print(f"❌ Test failed: {e}")
