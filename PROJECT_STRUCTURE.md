# 🚌 Bus Route Optimization System - Project Structure

## 📁 Project Organization

```
Geekhacthon/
├── 📱 Messaging System
│   ├── messaging_simulator.py      # Core messaging simulator
│   ├── web_messaging.py           # Web interface for messaging
│   └── requirements_messaging.txt # Messaging dependencies
│
├── 🗺️ Route Planning System  
│   └── routePlanning/
│       ├── dynamic_route_optimizer.py  # Core optimization engine
│       ├── web_server.py              # Route visualization server
│       ├── requirements.txt           # Route planning dependencies
│       └── templates/
│           └── index.html            # Route visualization template
│
├── 🚀 System Management
│   ├── start_system.py              # Unified startup script
│   └── PROJECT_STRUCTURE.md         # This file
│
├── 📊 React Frontend (Optional)
│   └── messagingSimulator/          # React-based UI (requires Node.js)
│       ├── src/
│       ├── package.json
│       └── vite.config.js
│
└── 📄 Documentation
    ├── README.md                    # Main project documentation
    └── .gitignore                   # Git ignore rules
```

## 🚀 Quick Start

### Option 1: Complete System (Recommended)
```bash
python start_system.py
# Choose option 1 for both servers
```

### Option 2: Individual Components

#### Messaging Simulator Web Interface
```bash
python web_messaging.py
# Access: http://localhost:5000
```

#### Route Optimization Web Interface  
```bash
cd routePlanning
python web_server.py
# Access: http://localhost:5001
```

#### Command Line Simulator
```bash
python messaging_simulator.py
# Interactive command line interface
```

## 🔧 System Components

### 📱 Messaging System
- **Purpose**: Simulate user pickup requests
- **Features**: 
  - Natural language processing
  - Web chat interface
  - Direct DynamoDB integration
  - Real-time request creation

### 🗺️ Route Optimization
- **Purpose**: Optimize vehicle routes and visualize results
- **Features**:
  - Multi-vehicle route optimization
  - Interactive map visualization
  - Environmental impact tracking
  - Real-time filtering and controls

### 🚀 System Integration
- **Unified startup**: Single script to run entire system
- **Cross-component communication**: Shared DynamoDB backend
- **Real-time updates**: Live optimization of new requests

## 💻 Usage Examples

### Creating Pickup Requests

#### Web Interface (http://localhost:5000)
```
User: "I want to go from downtown to airport at 14:30"
Bot: "✅ Pickup request created successfully! Request ID: abc-123..."
```

#### Command Line
```bash
python messaging_simulator.py "I need a ride from university to mall at 16:00"
```

### Running Optimization

#### Web Interface
1. Create several pickup requests
2. Click "🚌 Run Route Optimization" 
3. View generated map with optimized routes

#### Direct Access (http://localhost:5001)
- Set time filters
- View real-time route optimization
- Interactive map controls

## 🔧 Configuration

### AWS Setup Required
- DynamoDB tables: `requests`, `stops`, `vehicles`
- Amazon Location Service: Route calculator
- AWS credentials configured

### Environment Variables
```bash
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
```

## 🛠️ Development

### Adding New Features
1. **Messaging**: Modify `messaging_simulator.py`
2. **Optimization**: Update `routePlanning/dynamic_route_optimizer.py`
3. **Web UI**: Edit template files or Flask routes

### Testing
```bash
# Test messaging system
python messaging_simulator.py

# Test optimization
cd routePlanning
python dynamic_route_optimizer.py
```

## 🚨 Troubleshooting

### Common Issues

#### Port Already in Use
```bash
# Kill existing processes
netstat -ano | findstr :5000
taskkill /PID <process_id> /F
```

#### AWS Connection Issues
- Verify AWS credentials
- Check DynamoDB table permissions
- Ensure Location Service access

#### Missing Dependencies
```bash
pip install -r requirements_messaging.txt
pip install -r routePlanning/requirements.txt
```

## 📈 System Flow

1. **User Request** → Messaging Interface
2. **Request Processing** → DynamoDB Storage  
3. **Route Optimization** → Algorithm Processing
4. **Visualization** → Interactive Map Display
5. **Real-time Updates** → Live System Monitoring

## 🎯 Next Steps

- [ ] Enhanced NLP for request processing
- [ ] Real-time WebSocket updates
- [ ] Mobile app integration
- [ ] Advanced optimization algorithms
- [ ] Performance monitoring dashboard