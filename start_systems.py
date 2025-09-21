#!/usr/bin/env python3
"""
Startup Script for Both Systems
- Route Optimization (Python Flask)
- Messaging Simulator (React/Vite)
"""

import subprocess
import sys
import os
import time
import threading
from datetime import datetime

def run_route_server():
    """Run the Python route optimization server"""
    print("🗺️ Starting Route Optimization Server (Python Flask)...")
    try:
        route_dir = os.path.join(os.getcwd(), "routePlanning")
        subprocess.run([sys.executable, "web_server.py"], cwd=route_dir)
    except KeyboardInterrupt:
        print("\n🗺️ Route server stopped")
    except Exception as e:
        print(f"❌ Error starting route server: {e}")

def run_messaging_simulator():
    """Run the React messaging simulator"""
    print("📱 Starting Messaging Simulator (React/Vite)...")
    try:
        messaging_dir = os.path.join(os.getcwd(), "messagingSimulator")
        
        # Try different npm commands
        npm_commands = ["npm", "npm.cmd", "npx"]
        npm_found = False
        
        for npm_cmd in npm_commands:
            try:
                # Test if npm is available
                subprocess.run([npm_cmd, "--version"], capture_output=True, check=True)
                npm_found = True
                print(f"✅ Found {npm_cmd}")
                
                # Check if node_modules exists
                node_modules_path = os.path.join(messaging_dir, "node_modules")
                if not os.path.exists(node_modules_path):
                    print("📦 Installing dependencies...")
                    subprocess.run([npm_cmd, "install"], cwd=messaging_dir, check=True)
                
                # Start the development server
                print("🚀 Starting React development server...")
                subprocess.run([npm_cmd, "run", "dev"], cwd=messaging_dir)
                break
                
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue
        
        if not npm_found:
            print("❌ Node.js/npm not found in PATH.")
            print("   Please restart your terminal after installing Node.js")
            print("   Or run manually: cd messagingSimulator && npm run dev")
            
    except KeyboardInterrupt:
        print("\n📱 Messaging simulator stopped")
    except Exception as e:
        print(f"❌ Error starting messaging simulator: {e}")

def main():
    """Main startup function"""
    print("="*60)
    print("🚌 Bus Route Optimization System")
    print("="*60)
    print(f"⏰ Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    print("📋 System Components:")
    print("  🗺️ Route Optimization (Python): http://localhost:5001")
    print("  📱 Messaging Simulator (React): http://localhost:5173")
    print()
    
    choice = input("Choose startup mode:\n1. Both systems (recommended)\n2. Route optimization only (Python)\n3. Messaging simulator only (React)\n4. Python messaging alternative\n5. Show manual startup instructions\nEnter choice (1-5): ").strip()
    
    if choice == "1":
        print("\n🚀 Starting both systems...")
        
        # Start route server in a separate thread
        route_thread = threading.Thread(target=run_route_server, daemon=True)
        route_thread.start()
        
        # Wait a moment for the first server to start
        time.sleep(2)
        
        # Start messaging simulator in main thread
        try:
            run_messaging_simulator()
        except KeyboardInterrupt:
            print("\n👋 Shutting down system...")
    
    elif choice == "2":
        print("\n🗺️ Starting route optimization only...")
        run_route_server()
    
    elif choice == "3":
        print("\n📱 Starting messaging simulator only...")
        run_messaging_simulator()
    
    elif choice == "4":
        print("\n💻 Starting Python messaging alternative...")
        try:
            subprocess.run([sys.executable, "simple_web.py"])
        except Exception as e:
            print(f"Error starting Python messaging: {e}")
    
    elif choice == "5":
        print("\n🔧 Manual startup instructions:")
        print("Terminal 1 - Route Optimization:")
        print("  cd routePlanning")
        print("  python web_server.py")
        print("\nTerminal 2 - Messaging Simulator:")
        print("  cd messagingSimulator")
        print("  npm run dev")
        return
    
    else:
        print("❌ Invalid choice. Exiting.")
        return

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 System shutdown complete!")
    except Exception as e:
        print(f"\n❌ System error: {e}")
        sys.exit(1)