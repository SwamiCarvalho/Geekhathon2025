from flask import Flask, request, send_file, redirect
from dynamic_route_optimizer import DynamicRouteOptimizer
import webbrowser
import threading
import time
import os

app = Flask(__name__)
optimizer = DynamicRouteOptimizer('requests', 'stops', 'vehicles', 'MyRouteCalculator')
current_map_file = None

@app.route('/')
def index():
    global current_map_file
    start_time = request.args.get('start')
    end_time = request.args.get('end')
    
    # Generate new map with filters
    assignments, routes, map_file = optimizer.run_optimization(start_time, end_time)
    current_map_file = map_file
    
    if map_file and os.path.exists(map_file):
        return send_file(map_file)
    else:
        return "<h1>Error generating map</h1>", 500

@app.route('/filter')
def filter_routes():
    start_time = request.args.get('start')
    end_time = request.args.get('end')
    return redirect(f'/?start={start_time}&end={end_time}' if start_time and end_time else '/')

def open_browser():
    time.sleep(1)
    webbrowser.open('http://localhost:5000')

if __name__ == '__main__':
    import os
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        threading.Thread(target=open_browser).start()
    app.run(debug=True, use_reloader=True, port=5000, host='127.0.0.1')