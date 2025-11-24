#!/usr/bin/env python3
"""
Test script for MCP protocol endpoints (/mcp and /sse)

This script tests if the MCP server is properly exposing the MCP protocol endpoints
that Inspector can connect to.
"""

import requests
import json
import sys

def test_endpoint(url, method="GET", data=None, headers=None):
    """Test an endpoint and return the result"""
    try:
        if method == "GET":
            response = requests.get(url, headers=headers, timeout=5)
        elif method == "POST":
            response = requests.post(url, json=data, headers=headers, timeout=5)
        elif method == "OPTIONS":
            response = requests.options(url, headers=headers, timeout=5)
        else:
            return False, f"Unsupported method: {method}"
        
        return response.status_code, response.text[:200] if response.text else ""
    except requests.exceptions.RequestException as e:
        return False, str(e)

def main():
    if len(sys.argv) < 2:
        base_url = "http://localhost:8080"
        print(f"No URL provided, using default: {base_url}")
    else:
        base_url = sys.argv[1].rstrip('/')
    
    print(f"\n🧪 Testing MCP endpoints at: {base_url}\n")
    print("=" * 60)
    
    # Test health endpoint
    print("\n1. Testing /health endpoint...")
    status, text = test_endpoint(f"{base_url}/health")
    if status == 200:
        print(f"   ✅ Health check passed: {status}")
        try:
            health_data = json.loads(text)
            print(f"   📊 Service: {health_data.get('service', 'N/A')}")
        except:
            pass
    else:
        print(f"   ❌ Health check failed: {status}")
    
    # Test /mcp endpoint (MCP protocol)
    print("\n2. Testing /mcp endpoint (MCP protocol)...")
    status, text = test_endpoint(f"{base_url}/mcp", method="OPTIONS")
    if status in [200, 204]:
        print(f"   ✅ /mcp OPTIONS passed: {status}")
    else:
        print(f"   ⚠️  /mcp OPTIONS returned: {status}")
    
    # Test POST to /mcp (MCP protocol message)
    print("\n3. Testing POST /mcp (MCP protocol message)...")
    mcp_message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "test-client",
                "version": "1.0.0"
            }
        }
    }
    status, text = test_endpoint(
        f"{base_url}/mcp",
        method="POST",
        data=mcp_message,
        headers={"Content-Type": "application/json"}
    )
    if status == 200:
        print(f"   ✅ /mcp POST passed: {status}")
        try:
            response = json.loads(text)
            if "result" in response or "error" in response:
                print(f"   📊 Got MCP response")
        except:
            pass
    elif status == 404:
        print(f"   ❌ /mcp endpoint not found (404)")
    else:
        print(f"   ⚠️  /mcp POST returned: {status}")
    
    # Test /sse endpoint
    print("\n4. Testing /sse endpoint (Server-Sent Events)...")
    status, text = test_endpoint(
        f"{base_url}/sse",
        method="GET",
        headers={"Accept": "text/event-stream"}
    )
    if status == 200:
        print(f"   ✅ /sse endpoint accessible: {status}")
    elif status == 404:
        print(f"   ❌ /sse endpoint not found (404)")
    else:
        print(f"   ⚠️  /sse returned: {status}")
    
    # Test REST API endpoints (should still work)
    print("\n5. Testing REST API endpoints...")
    status, text = test_endpoint(f"{base_url}/mcp/list_tables")
    if status == 200:
        print(f"   ✅ /mcp/list_tables passed: {status}")
    else:
        print(f"   ⚠️  /mcp/list_tables returned: {status}")
    
    print("\n" + "=" * 60)
    print("\n📝 Summary:")
    print("   - If /mcp and /sse return 200 or 204, MCP protocol is working")
    print("   - If they return 404, FastMCP endpoints are not mounted")
    print("   - Inspector can connect if /mcp endpoint responds to POST requests")
    print("\n")

if __name__ == "__main__":
    try:
        import requests
    except ImportError:
        print("❌ Error: 'requests' module not found. Install it with: pip install requests")
        sys.exit(1)
    
    main()

