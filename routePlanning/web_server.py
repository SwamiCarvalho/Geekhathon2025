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
    try:
        start_time = request.args.get('start')
        end_time = request.args.get('end')
        max_wait = int(request.args.get('maxwait', 15))
        max_travel = int(request.args.get('maxtravel', 20))
        
        print(f"Web request: start={start_time}, end={end_time}, maxwait={max_wait}, maxtravel={max_travel}")
        
        # Generate new map with filters
        assignments, routes, map_file = optimizer.run_optimization(start_time, end_time, max_wait, max_travel)
        current_map_file = map_file
        
        if map_file and os.path.exists(map_file):
            print(f"Successfully generated map: {map_file}")
            return send_file(map_file)
        else:
            error_msg = f"Map generation failed: file={map_file}, exists={os.path.exists(map_file) if map_file else False}"
            print(error_msg)
            return f"<h1>Error generating map</h1><p>{error_msg}</p>", 500
    except Exception as e:
        error_msg = f"Exception in web server: {str(e)}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        return f"<h1>Error generating map</h1><p>{error_msg}</p><pre>{traceback.format_exc()}</pre>", 500

@app.route('/filter')
def filter_routes():
    start_time = request.args.get('start')
    end_time = request.args.get('end')
    max_wait = request.args.get('maxwait', 15)
    max_travel = request.args.get('maxtravel', 45)
    
    params = []
    if start_time: params.append(f'start={start_time}')
    if end_time: params.append(f'end={end_time}')
    if max_wait != '15': params.append(f'maxwait={max_wait}')
    if max_travel != '20': params.append(f'maxtravel={max_travel}')
    
    query_string = '&'.join(params)
    return redirect(f'/?{query_string}' if query_string else '/')

def open_browser():
    time.sleep(1)
    webbrowser.open('http://localhost:5001')

if __name__ == '__main__':
    import os
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        threading.Thread(target=open_browser).start()
    app.run(debug=True, use_reloader=True, port=5001, host='127.0.0.1')