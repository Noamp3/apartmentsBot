import asyncio
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ai_engine import GeminiAIEngine, RateLimiter, RateLimitExceeded
from config import settings

# Mock RateLimiter to fail quickly
class MockRateLimiter(RateLimiter):
    def __init__(self, limit=1):
        super().__init__(daily_limit=limit)
        self.count = 0
        
    async def acquire(self):
        if self.count >= self.daily_limit:
            raise RateLimitExceeded("Mock limit reached")
        self.count += 1
        return True

async def test_rotation():
    print("Testing model rotation...")
    
    # Override settings for test
    # settings.GEMINI_MODELS_LIST = ... # Removed
    settings.GEMINI_MODEL = "model-a,model-b,model-c"
    
    # Initialize engine
    # We need to monkeypatch the RateLimiter creation inside GeminiAIEngine 
    # or just manually inject our mock limiters after init if possible, 
    # but init creates them.
    
    # EASIER: Subclass GeminiAIEngine for testing to inject mock limiters
    class TestEngine(GeminiAIEngine):
        def __init__(self):
            super().__init__(api_key="dummy", model="model-a")
            # Force replace limiters with mocks
            self.limiters = {
                m: MockRateLimiter(limit=1) for m in self.models
            }
            # Mock the client to avoid real calls
            class MockClient:
                class Models:
                    def generate_content(self, model, contents):
                        return type('obj', (object,), {'text': f"Response from {model}"})
                models = Models()
            self.client = MockClient()

    engine = TestEngine()
    
    print(f"Initial model: {engine.current_model}")
    
    # Call 1: Should succeed on model-a
    res1 = await engine.generate_content("test1")
    print(f"Call 1 Result: {res1}")
    if "model-a" not in res1:
        print("FAIL: Call 1 did not use model-a")
        return
        
    # Call 2: Should fail model-a (limit 1), rotate to model-b, and succeed
    print(f"Current model before call 2: {engine.current_model}")
    res2 = await engine.generate_content("test2")
    print(f"Call 2 Result: {res2}")
    if "model-b" not in res2:
        print("FAIL: Call 2 did not rotate to model-b")
        return

    # Call 3: Should fail model-b (limit 1), rotate to model-c, and succeed
    res3 = await engine.generate_content("test3")
    print(f"Call 3 Result: {res3}")
    if "model-c" not in res3:
        print("FAIL: Call 3 did not rotate to model-c")
        return

    # Call 4: Should fail model-c (limit 1), rotate to model-a (which is full), 
    # then fail model-a again... eventually should loop or fail if all full.
    # In my logic, it just loops. The 'attempts_across_models' prevents infinite loop.
    # Since all limiters are full (count=1, limit=1), it should eventually raise exception.
    
    print("Testing exhaustion...")
    try:
        await engine.generate_content("test4")
        print("FAIL: Should have raised exception when all models exhausted")
    except Exception as e:
        print(f"SUCCESS: Caught expected exception: {e}")

if __name__ == "__main__":
    asyncio.run(test_rotation())
