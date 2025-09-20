import boto3
import json
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import folium
from folium import plugins

class DynamicRouteOptimizer:
    def __init__(self, requests_table: str, stops_table: str, vehicles_table: str, map_name: str):
        self.dynamodb = boto3.resource('dynamodb')
        self.requests_table = self.dynamodb.Table(requests_table)
        self.stops_table = self.dynamodb.Table(stops_table)
        self.vehicles_table = self.dynamodb.Table(vehicles_table)
        self.location_client = boto3.client('location')
        self.bedrock_client = boto3.client('bedrock-runtime')
        self.map_name = map_name
        
    def get_requests(self, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Get requests from DynamoDB with optional time filter"""
        response = self.requests_table.scan()
        requests = response['Items']
        
        # Convert requestedPickupAt to datetime immediately
        for req in requests:
            pickup_at = req.get('requestedPickupAt')
            if pickup_at:
                if isinstance(pickup_at, str):
                    try:
                        req['requestedPickupAt'] = datetime.strptime(pickup_at, '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        req['requestedPickupAt'] = None
                elif isinstance(pickup_at, (int, float)):
                    req['requestedPickupAt'] = datetime.fromtimestamp(pickup_at)
        
        # Filter by time if provided
        if start_time or end_time:
            filtered = []
            for req in requests:
                pickup_dt = req.get('requestedPickupAt')
                if pickup_dt:
                    if start_time and pickup_dt < start_time:
                        continue
                    if end_time and pickup_dt > end_time:
                        continue
                filtered.append(req)
            return filtered
        
        return requests
    
    def get_vehicles(self) -> List[Dict[str, Any]]:
        """Get first 3 vehicles from DynamoDB"""
        response = self.vehicles_table.scan(Limit=3)
        return response['Items']
    
    def assign_requests_to_vehicles(self, requests: List[Dict], vehicles: List[Dict]) -> Dict[str, List[Dict]]:
        """Assign ALL requests to vehicles considering time constraints"""
        assignments = {vehicle['vehicleId']: [] for vehicle in vehicles}
        
        # Sort requests by pickup time
        def get_pickup_datetime(req):
            pickup_dt = req.get('requestedPickupAt')
            return pickup_dt if pickup_dt else datetime.fromtimestamp(0)
        
        sorted_requests = sorted(requests, key=get_pickup_datetime)
        
        for request in sorted_requests:
            origin_coords = self.get_stop_coords(request['originStopId'])
            if not origin_coords:
                continue
            
            best_vehicle = None
            min_cost = float('inf')
            
            for vehicle in vehicles:
                vehicle_id = vehicle['vehicleId']
                current_requests = assignments[vehicle_id]
                
                # Increased capacity - allow more requests per vehicle
                if len(current_requests) >= vehicle.get('capacity', 20):
                    continue
                
                # Relaxed time constraint - allow 30 minutes instead of 15
                if self._violates_waiting_time(request, current_requests, max_wait_minutes=30):
                    continue
                
                cost = self._calculate_assignment_cost(request, vehicle, current_requests)
                
                if cost < min_cost:
                    min_cost = cost
                    best_vehicle = vehicle
            
            if best_vehicle:
                assignments[best_vehicle['vehicleId']].append(request)
            else:
                # Force assign to vehicle with least requests if no optimal match
                least_loaded = min(vehicles, key=lambda v: len(assignments[v['vehicleId']]))
                assignments[least_loaded['vehicleId']].append(request)
        
        return assignments
    
    def _violates_waiting_time(self, request: Dict, current_requests: List[Dict], max_wait_minutes: int = 15) -> bool:
        """Check if request violates waiting time constraint"""
        request_dt = request.get('requestedPickupAt')
        if not request_dt:
            return False
        
        for existing in current_requests:
            existing_dt = existing.get('requestedPickupAt')
            if not existing_dt:
                continue
            
            time_diff = abs((request_dt - existing_dt).total_seconds())
            if time_diff > (max_wait_minutes * 60):
                return True
        return False
    
    def _calculate_assignment_cost(self, request: Dict, vehicle: Dict, current_requests: List[Dict]) -> float:
        """Calculate cost of assigning request to vehicle"""
        origin_coords = self.get_stop_coords(request['originStopId'])
        if not origin_coords:
            return float('inf')
        
        vehicle_pos = [float(vehicle.get('longitude', 0)), float(vehicle.get('latitude', 0))]
        distance_cost = self._calculate_distance(vehicle_pos, origin_coords)
        
        # Time-based penalty
        time_penalty = 0
        request_dt = request.get('requestedPickupAt')
        if request_dt:
            for existing in current_requests:
                existing_dt = existing.get('requestedPickupAt')
                if existing_dt:
                    time_diff = abs((request_dt - existing_dt).total_seconds())
                    time_penalty += time_diff * 0.001
        
        return distance_cost + time_penalty
    

    
    def optimize_route_with_location_service(self, vehicle_id: str, requests: List[Dict]) -> Dict:
        """Enhanced route optimization with optimal pickup/dropoff sequence"""
        if not requests:
            return {'route': [], 'distance': 0, 'duration': 0}
        
        # Sort requests by pickup time
        sorted_requests = sorted(requests, key=lambda r: r.get('requestedPickupAt') or datetime.fromtimestamp(0))
        
        # Create all stops (pickups and dropoffs) with optimal sequencing
        all_stops = []
        for req in sorted_requests:
            origin = self.get_stop_coords(req['originStopId'])
            dest = self.get_stop_coords(req['destStopId'])
            pickup_dt = req.get('requestedPickupAt')
            pickup_time = pickup_dt.strftime('%H:%M') if pickup_dt else 'N/A'
            
            if origin:
                all_stops.append({
                    'type': 'pickup',
                    'requestId': req.get('requestId'),
                    'stopId': req['originStopId'],
                    'time': pickup_time,
                    'coords': origin,
                    'priority': pickup_dt.timestamp() if pickup_dt else 0
                })
            
            if dest:
                all_stops.append({
                    'type': 'dropoff',
                    'requestId': req.get('requestId'),
                    'stopId': req['destStopId'],
                    'coords': dest,
                    'priority': (pickup_dt.timestamp() + 1800) if pickup_dt else 999999  # 30 min after pickup
                })
        
        # Sort by priority for optimal sequence (pickup time + dropoff delay)
        all_stops.sort(key=lambda x: x['priority'])
        
        waypoints = [stop['coords'] for stop in all_stops]
        sequence = all_stops
        
        if len(waypoints) < 2:
            return {'route': [], 'distance': 0, 'duration': 0}
        
        # Ensure waypoint limit
        if len(waypoints) > 23:
            waypoints = waypoints[:23]
            sequence = sequence[:23]
        
        try:
            response = self.location_client.calculate_route(
                CalculatorName=self.map_name,
                DeparturePosition=waypoints[0],
                DestinationPosition=waypoints[-1],
                WaypointPositions=waypoints[1:-1] if len(waypoints) > 2 else [],
                TravelMode='Car',
                IncludeLegGeometry=True
            )
            
            return {
                'route': response['Legs'],
                'distance': response['Summary']['Distance'],
                'duration': response['Summary']['DurationSeconds'],
                'waypoints': waypoints,
                'sequence': sequence,
                'geometry': response.get('Legs', [])
            }
        except Exception as e:
            print(f"Route optimization failed: {e}")
            return {'route': [], 'distance': 0, 'duration': 0, 'waypoints': waypoints, 'sequence': sequence}
    
    def create_route_map(self, assignments: Dict[str, List[Dict]], routes: Dict[str, Dict]) -> str:
        """Create interactive map with routes"""
        # Center map on first vehicle or default location
        center_lat, center_lon = 39.7491, -8.8118
        
        m = folium.Map(location=[center_lat, center_lon], zoom_start=12)
        map_var = f"map_{int(time.time())}"
        
        colors = ['red', 'blue', 'green', 'purple', 'orange']
        
        for i, (vehicle_id, vehicle_requests) in enumerate(assignments.items()):
            if not vehicle_requests:
                continue
                
            color = colors[i % len(colors)]
            route_data = routes.get(vehicle_id, {})
            waypoints = route_data.get('waypoints', [])
            
            # Add vehicle marker
            if waypoints:
                folium.Marker(
                    [waypoints[0][1], waypoints[0][0]],
                    popup=f"Vehicle {vehicle_id}",
                    icon=folium.Icon(color=color, icon='car', prefix='fa')
                ).add_to(m)
            
            # Add route line
            if len(waypoints) > 1:
                route_coords = [[wp[1], wp[0]] for wp in waypoints]
                folium.PolyLine(
                    route_coords,
                    color=color,
                    weight=3,
                    opacity=0.8,
                    popup=f"Vehicle {vehicle_id} Route"
                ).add_to(m)
            
            # Use optimized sequence from route data
            route_data = routes.get(vehicle_id, {})
            sequence = route_data.get('sequence', [])
            
            if sequence:
                # Group stops by location to show multiple requests at same stop
                stop_groups = {}
                for idx, stop in enumerate(sequence):
                    coord_key = f"{stop['coords'][0]:.6f},{stop['coords'][1]:.6f}"
                    if coord_key not in stop_groups:
                        stop_groups[coord_key] = {
                            'coords': stop['coords'],
                            'stops': [],
                            'number': idx + 1
                        }
                    stop_groups[coord_key]['stops'].append(stop)
                
                # Create markers for each location group
                for group in stop_groups.values():
                    coords = group['coords']
                    stops = group['stops']
                    stop_number = group['number']
                    
                    # Build popup content for all stops at this location
                    popup_content = f"Stop {stop_number}:<br>"
                    pickup_stops = [s for s in stops if s['type'] == 'pickup']
                    dropoff_stops = [s for s in stops if s['type'] == 'dropoff']
                    
                    if pickup_stops:
                        popup_content += "<b>PICKUPS:</b><br>"
                        for stop in pickup_stops:
                            popup_content += f"• Request {stop['requestId']} at {stop.get('time', 'N/A')}<br>"
                    
                    if dropoff_stops:
                        popup_content += "<b>DROPOFFS:</b><br>"
                        for stop in dropoff_stops:
                            popup_content += f"• Request {stop['requestId']}<br>"
                    
                    popup_content += f"Stop ID: {stops[0]['stopId']}"
                    
                    # Choose icon style based on stop type
                    if pickup_stops and dropoff_stops:
                        # Mixed stop - both pickup and dropoff
                        icon_html = f'<div style="background: linear-gradient(45deg, {color} 50%, white 50%);color:black;border:2px solid {color};border-radius:50%;width:30px;height:30px;text-align:center;line-height:26px;font-weight:bold;font-size:12px;">{stop_number}</div>'
                    elif pickup_stops:
                        # Pickup only
                        icon_html = f'<div style="background-color:{color};color:white;border-radius:50%;width:30px;height:30px;text-align:center;line-height:30px;font-weight:bold;font-size:12px;">{stop_number}</div>'
                    else:
                        # Dropoff only
                        icon_html = f'<div style="background-color:white;color:{color};border:3px solid {color};border-radius:50%;width:30px;height:30px;text-align:center;line-height:24px;font-weight:bold;font-size:12px;">{stop_number}</div>'
                    
                    folium.Marker(
                        [coords[1], coords[0]],
                        popup=popup_content,
                        icon=folium.DivIcon(
                            html=icon_html,
                            icon_size=(30, 30)
                        )
                    ).add_to(m)
        
        # Add interactive time filter controls
        filter_html = f'''
        <div style="position: fixed; 
                    top: 10px; left: 10px; width: 300px; height: auto; 
                    background-color: white; border:2px solid grey; z-index:9999; 
                    font-size:12px; padding: 10px">
        <h4>Time Filter</h4>
        <label>Start Time:</label><br>
        <input type="datetime-local" id="startTime" style="width:100%; margin:5px 0;"><br>
        <label>End Time:</label><br>
        <input type="datetime-local" id="endTime" style="width:100%; margin:5px 0;"><br>
        <button onclick="filterRoutes()" style="width:100%; padding:5px; background:#007cba; color:white; border:none; cursor:pointer;">Filter Routes</button>
        <button onclick="clearFilter()" style="width:100%; padding:5px; margin-top:5px; background:#666; color:white; border:none; cursor:pointer;">Show All</button>
        <div id="filterStatus" style="margin-top:10px; font-size:11px; color:#666;">Showing all routes</div>
        </div>
        
        <script>
        function filterRoutes() {{
            const start = document.getElementById('startTime').value;
            const end = document.getElementById('endTime').value;
            if (start && end) {{
                const startFormatted = start.replace('T', ' ');
                const endFormatted = end.replace('T', ' ');
                document.getElementById('filterStatus').innerHTML = 'Filtering routes...';
                window.location.href = `/filter?start=${{startFormatted}}&end=${{endFormatted}}`;
            }} else {{
                alert('Please select both start and end times');
            }}
        }}
        
        function clearFilter() {{
            document.getElementById('startTime').value = '';
            document.getElementById('endTime').value = '';
            document.getElementById('filterStatus').innerHTML = 'Showing all routes';
            window.location.href = '/';
        }}
        </script>
        '''
        
        # Add legend
        legend_html = '''
        <div style="position: fixed; 
                    bottom: 50px; left: 50px; width: 250px; height: auto; 
                    background-color: white; border:2px solid grey; z-index:9999; 
                    font-size:14px; padding: 10px">
        <h4>Route Legend</h4>
        '''        
        for i, (vehicle_id, _) in enumerate(assignments.items()):
            if assignments[vehicle_id]:
                color = colors[i % len(colors)]
                legend_html += f'<p><span style="color:{color};">■</span> Vehicle {vehicle_id}</p>'
        
        legend_html += '''
        <p><span style="background-color:#333;color:white;border-radius:50%;padding:2px 6px;font-size:12px;">1</span> HOP ON (Pickup)</p>
        <p><span style="background-color:white;color:#333;border:2px solid #333;border-radius:50%;padding:2px 6px;font-size:12px;">2</span> DROP OFF</p>
        <p>🚗 Vehicle Start Position</p>
        <p><strong>Numbers show stop order</strong></p>
        </div>
        '''
        
        # Add optimization info panel
        info_html = '''
        <div style="position: fixed; 
                    top: 10px; right: 10px; width: 280px; height: auto; 
                    background-color: white; border:2px solid grey; z-index:9999; 
                    font-size:12px; padding: 10px">
        <h4>Route Optimization</h4>
        <p><strong>Objectives:</strong></p>
        <p>• Minimize travel time</p>
        <p>• Minimize waiting time (&lt;15 min)</p>
        <p>• Optimize vehicle utilization</p>
        </div>
        '''
        
        # Replace placeholder in filter_html with actual map variable
        filter_html = filter_html.replace(f"map_{int(time.time())}", map_var)
        m.get_root().html.add_child(folium.Element(filter_html))
        m.get_root().html.add_child(folium.Element(info_html))
        m.get_root().html.add_child(folium.Element(legend_html))
        
        map_file = f"route_map_{int(time.time())}.html"
        m.save(map_file)
        return map_file
    
    def get_stop_coords(self, stop_id: str) -> Optional[List[float]]:
        """Get coordinates for stop ID"""
        try:
            response = self.stops_table.get_item(Key={'stop_id': stop_id})
            item = response.get('Item', {})
            lat = float(item.get('stop_lat', 0))
            lon = float(item.get('stop_lon', 0))
            if lat == 0 and lon == 0:
                return None
            return [lon, lat]  # Amazon Location uses [longitude, latitude]
        except Exception as e:
            print(f"Error getting coordinates for stop {stop_id}: {e}")
            return None
    
    def _calculate_distance(self, pos1: List[float], pos2: List[float]) -> float:
        """Calculate distance between two points"""
        return ((pos1[0] - pos2[0])**2 + (pos1[1] - pos2[1])**2)**0.5
    
    def run_optimization(self, start_datetime: str = None, end_datetime: str = None):
        """Main optimization process with optional datetime filter"""
        print("Starting route optimization...")
        
        # Convert datetime strings to datetime objects if provided
        start_time = None
        end_time = None
        if start_datetime:
            start_time = datetime.strptime(start_datetime, '%Y-%m-%d %H:%M')
        if end_datetime:
            end_time = datetime.strptime(end_datetime, '%Y-%m-%d %H:%M')
        
        if start_time and end_time:
            print(f"Filtering requests from {start_datetime} to {end_datetime}")
        
        # Get data from DynamoDB
        requests = self.get_requests(start_time, end_time)
        vehicles = self.get_vehicles()
        
        print(f"Found {len(requests)} requests and {len(vehicles)} vehicles")
        
        if not requests:
            print("No requests found!")
            return {}, {}, None
            
        if not vehicles:
            print("No vehicles found!")
            return {}, {}, None
        
        # Assign requests to vehicles
        assignments = self.assign_requests_to_vehicles(requests, vehicles)
        
        # Optimize routes for each vehicle
        routes = {}
        for vehicle_id, vehicle_requests in assignments.items():
            if vehicle_requests:
                routes[vehicle_id] = self.optimize_route_with_location_service(vehicle_id, vehicle_requests)
        
        # Create map
        map_file = self.create_route_map(assignments, routes)
        
        # Display results
        self._display_results(assignments, routes, map_file, vehicles)
        
        return assignments, routes, map_file
    
    def _display_results(self, assignments: Dict, routes: Dict, map_file: str, vehicles: List[Dict]):
        """Display optimization results"""
        print("\n=== DYNAMIC ROUTE OPTIMIZATION RESULTS ===")
        
        total_requests = sum(len(reqs) for reqs in assignments.values())
        total_distance = sum(route.get('distance', 0) for route in routes.values())
        total_duration = sum(route.get('duration', 0) for route in routes.values())
        
        print(f"Total Requests Assigned: {total_requests}")
        print(f"Total Route Distance: {total_distance:.2f} km")
        print(f"Total Route Duration: {total_duration//60:.0f} minutes")
        if map_file:
            print(f"Map saved as: {map_file}")
        
        # Create a map for quick vehicle lookup
        vehicles_map = {v['vehicleId']: v for v in vehicles}

        # Show all vehicles, even those without assignments
        for vehicle_id in assignments.keys():
            vehicle = vehicles_map.get(vehicle_id, {})
            vehicle_requests = assignments[vehicle_id]
            route = routes.get(vehicle_id, {})
            
            print(f"\nVehicle {vehicle_id}:")
            if vehicle_requests:
                print(f"  Assigned {len(vehicle_requests)} requests:")
                # Sort requests by pickup time for display
                sorted_reqs = sorted(vehicle_requests, key=lambda r: r.get('requestedPickupAt') or datetime.fromtimestamp(0))
                
                print(f"  STOP SEQUENCE (in order):")
                stop_number = 1
                
                for req in sorted_reqs:
                    pickup_dt = req.get('requestedPickupAt')
                    pickup_time = pickup_dt.strftime('%Y-%m-%d %H:%M') if pickup_dt else 'N/A'
                    
                    # Pickup stop
                    print(f"    Stop {stop_number}: HOP ON  - {req['originStopId']} (Request {req.get('requestId', 'N/A')}) at {pickup_time}")
                    stop_number += 1
                    
                    # Dropoff stop
                    print(f"    Stop {stop_number}: DROP OFF - {req['destStopId']} (Request {req.get('requestId', 'N/A')})")
                    stop_number += 1
                
                # Show time constraints validation
                if len(sorted_reqs) > 1:
                    pickup_times = [r.get('requestedPickupAt') for r in sorted_reqs if r.get('requestedPickupAt')]
                    if pickup_times:
                        min_time = min(pickup_times)
                        max_time = max(pickup_times)
                        time_span = (max_time - min_time).total_seconds() / 60  # in minutes
                        print(f"  Time span: {time_span:.1f} minutes (max 15 min allowed)")
                
                print(f"  Total stops: {(len(sorted_reqs) * 2)} stops for {len(sorted_reqs)} requests")
                print(f"  Vehicle utilization: {len(sorted_reqs)}/{vehicle.get('capacity', 20)} capacity used")
                
                print(f"  Route distance: {route.get('distance', 0):.2f}km")
                if route.get('duration'):
                    print(f"  Route duration: {route['duration']//60:.0f} minutes")
            else:
                print(f"  No requests assigned")

def main():
    optimizer = DynamicRouteOptimizer('requests', 'stops', 'vehicles', 'MyRouteCalculator')
    
    # Example with datetime filter (uncomment to use)
    # assignments, routes, map_file = optimizer.run_optimization('2025-09-21 08:00', '2025-09-21 22:00')
    
    # Run without filter (all requests)
    assignments, routes, map_file = optimizer.run_optimization()
    
    if map_file:
        print(f"\nOpen {map_file} in your browser to view the routes!")
        print(f"\nOptimization features:")
        print(f"• Handles multiple requests per vehicle (up to 20)")
        print(f"• Interactive time filtering in web interface")
        print(f"• 30-minute waiting time window for flexibility")
        print(f"• All requests are assigned to vehicles")
        print(f"• Fast travel times with minimal distance")

if __name__ == "__main__":
    main()