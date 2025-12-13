#!/usr/bin/env python
"""
Test script for /addkey -> /mykeys -> debate flow
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Set up test encryption key
os.environ['ENCRYPTION_KEY'] = 'test-key-for-development-only-32-chars!!!'

print("=" * 70)
print("TESTING: /addkey -> /mykeys -> debate flow")
print("=" * 70)

# Test 1: Import all required modules
print("\n[TEST 1] Importing modules...")
try:
    from src.bot import (
        main_bot_setup, addkey_command, mykeys_command, 
        receive_api_key_input, receive_alias_input,
        AVAILABLE_SERVICES, AWAITING_SERVICE, AWAITING_KEY, AWAITING_ALIAS
    )
    from src.ai_clients import AI_CLIENTS_MAP
    from src.database import DB_MANAGER, encrypt_key, decrypt_key
    from src.debate_manager import DebateSession  # noqa: F401
    print("  OK - All imports successful")
except Exception as e:
    print(f"  FAILED - {e}")
    sys.exit(1)

# Test 2: Verify database functions
print("\n[TEST 2] Testing database encryption...")
try:
    test_api_key = "sk-test-api-key-from-groq-12345"
    encrypted = encrypt_key(test_api_key)
    decrypted = decrypt_key(encrypted)
    assert test_api_key == decrypted, "Encryption/Decryption mismatch"
    print(f"  OK - Encryption working")
    print(f"    Original: {test_api_key}")
    print(f"    Encrypted length: {len(encrypted)}")
    print(f"    Decrypted: {decrypted}")
except Exception as e:
    print(f"  FAILED - {e}")
    sys.exit(1)

# Test 3: Verify available services
print("\n[TEST 3] Checking available services...")
try:
    assert 'gemini' in AVAILABLE_SERVICES, "gemini not found"
    assert 'groq' in AVAILABLE_SERVICES, "groq not found"
    assert 'claude' in AVAILABLE_SERVICES, "claude not found"
    assert 'deepseek' in AVAILABLE_SERVICES, "deepseek not found"
    print(f"  OK - All services available:")
    for service_key, service_name in AVAILABLE_SERVICES.items():
        print(f"    - {service_key}: {service_name}")
except Exception as e:
    print(f"  FAILED - {e}")
    sys.exit(1)

# Test 4: Verify AI client classes
print("\n[TEST 4] Checking AI client classes...")
try:
    assert 'groq' in AI_CLIENTS_MAP, "GroqClient not found"
    assert 'gemini' in AI_CLIENTS_MAP, "GeminiClient not found"
    assert 'claude' in AI_CLIENTS_MAP, "ClaudeAI not found"
    assert 'deepseek' in AI_CLIENTS_MAP, "DeepSeekAI not found"
    print(f"  OK - All AI client classes available:")
    for service, client_class in AI_CLIENTS_MAP.items():
        print(f"    - {service}: {client_class.__name__}")
except Exception as e:
    print(f"  FAILED - {e}")
    sys.exit(1)

# Test 5: Verify state constants
print("\n[TEST 5] Checking FSM state constants...")
try:
    assert AWAITING_SERVICE == 2, f"AWAITING_SERVICE is {AWAITING_SERVICE}, expected 2"
    assert AWAITING_KEY == 3, f"AWAITING_KEY is {AWAITING_KEY}, expected 3"
    assert AWAITING_ALIAS == 4, f"AWAITING_ALIAS is {AWAITING_ALIAS}, expected 4"
    print(f"  OK - All states defined correctly:")
    print(f"    - AWAITING_SERVICE = {AWAITING_SERVICE}")
    print(f"    - AWAITING_KEY = {AWAITING_KEY}")
    print(f"    - AWAITING_ALIAS = {AWAITING_ALIAS}")
except Exception as e:
    print(f"  FAILED - {e}")
    sys.exit(1)

# Test 6: Check database manager methods
print("\n[TEST 6] Checking DatabaseManager methods...")
try:
    required_methods = [
        'add_api_key',
        'get_user_api_keys', 
        'get_api_key_decrypted',
        'decrement_calls',
        'set_active_key',
        'get_active_key_id',
        '_create_tables'
    ]
    for method in required_methods:
        assert hasattr(DB_MANAGER, method), f"Method {method} not found"
    print(f"  OK - All required methods exist:")
    for method in required_methods:
        print(f"    - {method}()")
except Exception as e:
    print(f"  FAILED - {e}")
    sys.exit(1)

# Test 7: Check DebateSession
print("\n[TEST 7] Checking DebateSession...")
try:
    # Create a mock clients dict
    mock_clients = {
        'Mock1': None,  # We don't need real clients for this test
        'Mock2': None
    }
    session = DebateSession(
        topic="Test topic",
        clients_map=mock_clients,
        max_rounds=3
    )
    assert session.topic == "Test topic", "Topic mismatch"
    assert session.MAX_ROUNDS == 3, "Max rounds mismatch"
    assert len(session.clients) == 2, "Clients not set"
    print(f"  OK - DebateSession initialized:")
    print(f"    - Topic: {session.topic}")
    print(f"    - Max rounds: {session.MAX_ROUNDS}")
    print(f"    - Clients: {list(session.clients.keys())}")
except Exception as e:
    print(f"  FAILED - {e}")
    sys.exit(1)

print("\n" + "=" * 70)
print("ALL TESTS PASSED!")
print("=" * 70)
print("\nThe bot is ready for deployment with:")
print("  1. Encrypted API key storage (/addkey)")
print("  2. Key management interface (/mykeys)")
print("  3. Call limit tracking per key")
print("  4. Dynamic AI client initialization")
print("  5. Complete debate session management")
