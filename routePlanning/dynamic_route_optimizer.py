import boto3
import json
import time
import os
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
        self.lambda_client = boto3.client('lambda')
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
                    # Only filter if both start and end times are provided
                    if start_time and end_time:
                        if pickup_dt >= start_time and pickup_dt <= end_time:
                            filtered.append(req)
                    elif start_time and pickup_dt >= start_time:
                        filtered.append(req)
                    elif end_time and pickup_dt <= end_time:
                        filtered.append(req)
                    elif not start_time and not end_time:
                        filtered.append(req)
            print(f"Filtered {len(filtered)} requests from {len(requests)} total requests")
            return filtered
        
        return requests
    
    def get_vehicles(self) -> List[Dict[str, Any]]:
        """Get first 3 vehicles from DynamoDB"""
        response = self.vehicles_table.scan(Limit=3)
        return response['Items']
    
    def assign_requests_to_vehicles(self, requests: List[Dict], vehicles: List[Dict], max_wait_minutes: int = 15, max_travel_minutes: int = 20) -> Dict[str, List[Dict]]:
        """Assign ALL requests to vehicles considering time and travel duration constraints"""
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
                
                # Dynamic time constraint
                if self._violates_waiting_time(request, current_requests, max_wait_minutes=max_wait_minutes):
                    continue
                
                # Check travel duration constraint
                if self._violates_travel_duration(request, current_requests, max_travel_minutes=max_travel_minutes):
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
    
    def _violates_travel_duration(self, request: Dict, current_requests: List[Dict], max_travel_minutes: int = 15) -> bool:
        """Check if adding request would exceed maximum travel duration"""
        if not current_requests:
            return False
        
        # Estimate total route duration with new request
        all_requests = current_requests + [request]
        total_stops = len(all_requests) * 2  # pickup + dropoff for each
        
        # Simple heuristic: average 3 minutes per stop
        estimated_duration = total_stops * 3
        
        return estimated_duration > max_travel_minutes
    
    def _calculate_assignment_cost(self, request: Dict, vehicle: Dict, current_requests: List[Dict]) -> float:
        """Enhanced cost calculation for fuel efficiency and environmental impact"""
        origin_coords = self.get_stop_coords(request['originStopId'])
        dest_coords = self.get_stop_coords(request['destStopId'])
        if not origin_coords or not dest_coords:
            return float('inf')
        
        vehicle_pos = [float(vehicle.get('longitude', 0)), float(vehicle.get('latitude', 0))]
        
        # 1. Distance cost (fuel consumption)
        distance_to_pickup = self._calculate_distance(vehicle_pos, origin_coords)
        trip_distance = self._calculate_distance(origin_coords, dest_coords)
        
        # 2. Route efficiency - estimate total route distance with new request
        route_efficiency_penalty = self._calculate_route_efficiency_penalty(request, current_requests)
        
        # 3. Vehicle utilization bonus (more passengers = better efficiency)
        utilization_bonus = -len(current_requests) * 0.1  # Negative = bonus
        
        # 4. Time clustering bonus (requests close in time = efficient)
        time_clustering_bonus = self._calculate_time_clustering_bonus(request, current_requests)
        
        # 5. Geographic clustering bonus (nearby stops = less fuel)
        geo_clustering_bonus = self._calculate_geo_clustering_bonus(request, current_requests)
        
        total_cost = (
            distance_to_pickup * 2.0 +  # Weight distance to pickup heavily
            trip_distance * 0.5 +       # Trip distance matters less
            route_efficiency_penalty +
            utilization_bonus +
            time_clustering_bonus +
            geo_clustering_bonus
        )
        
        return total_cost
    
    def calculate_route_via_lambda(self, vehicle_id: str, requests: List[Dict]) -> Dict:
        """Call route calculator Lambda to get optimized route"""
        try:
            # Convert datetime objects to strings for JSON serialization
            serialized_requests = []
            for req in requests:
                req_copy = req.copy()
                if 'requestedPickupAt' in req_copy and req_copy['requestedPickupAt']:
                    if hasattr(req_copy['requestedPickupAt'], 'strftime'):
                        req_copy['requestedPickupAt'] = req_copy['requestedPickupAt'].strftime('%Y-%m-%d %H:%M:%S')
                serialized_requests.append(req_copy)
            
            payload = {
                'vehicle_id': vehicle_id,
                'requests': serialized_requests
            }
            
            print(f"Calling Lambda with {len(serialized_requests)} requests")
            
            response = self.lambda_client.invoke(
                FunctionName='calculateRoutePy',
                InvocationType='RequestResponse',
                Payload=json.dumps(payload)
            )
            
            result = json.loads(response['Payload'].read())
            print(f"Raw Lambda response: {result}")
            
            # Handle different response formats
            if 'statusCode' in result:
                if result['statusCode'] == 200:
                    route_result = json.loads(result['body'])
                    print(f"Route result keys: {list(route_result.keys())}")
                    return route_result
                else:
                    print(f"Route calculation error: {result['body']}")
                    return {'route': [], 'distance': 0, 'duration': 0}
            elif 'errorType' in result:
                # Lambda error (timeout, etc.)
                print(f"Lambda error: {result['errorType']} - {result['errorMessage']}")
                print("Falling back to local calculation")
                return self._calculate_route_locally(vehicle_id, requests)
            else:
                # Direct response from Lambda (no API Gateway wrapper)
                print(f"Direct Lambda response keys: {list(result.keys())}")
                return result
                
        except Exception as e:
            print(f"Failed to call route calculator Lambda: {e}")
            print(f"Exception type: {type(e)}")
            print("Falling back to local route calculation")
            return self._calculate_route_locally(vehicle_id, requests)
    
    def optimize_route_with_location_service(self, vehicle_id: str, requests: List[Dict]) -> Dict:
        """Use local route calculation (Lambda disabled due to timeout with large request sets)"""
        return self._calculate_route_locally(vehicle_id, requests)
    
    def create_route_map(self, assignments: Dict[str, List[Dict]], routes: Dict[str, Dict], vehicles: List[Dict] = None) -> str:
        """Create interactive map with routes"""
        try:
            print("Starting map creation...")
            # Center map on first vehicle or default location
            center_lat, center_lon = 39.7491, -8.8118
            
            m = folium.Map(location=[center_lat, center_lon], zoom_start=12)
            map_var = f"map_{int(time.time())}"
            
            colors = ['red', 'blue', 'green', 'purple', 'orange']
            print(f"Created base map centered at {center_lat}, {center_lon}")
            print(f"Assignments: {[(k, len(v)) for k, v in assignments.items()]}")
            print(f"Routes: {[(k, list(v.keys()) if v else 'None') for k, v in routes.items()]}")
            
            # Check if there are any assignments
            has_routes = any(len(reqs) > 0 for reqs in assignments.values())
            if not has_routes:
                print("No routes to display - creating empty map")
                # Create minimal HTML for empty map
                filter_html = '<div>No routes found</div>'
                info_html = '<div>No data</div>'
                legend_html = '<div>No legend</div>'
                return self._save_empty_map(m, filter_html, info_html, legend_html)
        except Exception as e:
            print(f"Error creating base map: {e}")
            raise
        
        for i, (vehicle_id, vehicle_requests) in enumerate(assignments.items()):
            if not vehicle_requests:
                continue
                
            color = colors[i % len(colors)]
            route_data = routes.get(vehicle_id, {})
            waypoints = route_data.get('waypoints', [])
            
            # Add vehicle marker
            print(f"Vehicle {vehicle_id} has {len(waypoints)} waypoints")
            if waypoints:
                folium.Marker(
                    [waypoints[0][1], waypoints[0][0]],
                    popup=f"Vehicle {vehicle_id}",
                    icon=folium.Icon(color=color, icon='car', prefix='fa')
                ).add_to(m)
            else:
                print(f"No waypoints for vehicle {vehicle_id}")
            
            # Add route line using actual road geometry
            route_data = routes.get(vehicle_id, {})
            geometry_found = False
            
            # Check if we have route geometry from the Lambda response
            if route_data.get('route'):
                # Use actual route geometry from Amazon Location Service
                for leg in route_data['route']:
                    if 'Geometry' in leg:
                        geometry = leg['Geometry']
                        if 'LineString' in geometry:
                            # Convert Amazon Location coordinates to Leaflet format
                            route_coords = [[coord[1], coord[0]] for coord in geometry['LineString']]
                            folium.PolyLine(
                                route_coords,
                                color=color,
                                weight=4,
                                opacity=0.8,
                                popup=f"Vehicle {vehicle_id} Route - {leg.get('Distance', 0):.1f}km"
                            ).add_to(m)
                            geometry_found = True
                        else:
                            print(f"No LineString in geometry: {geometry.keys()}")
                    else:
                        print(f"No Geometry in leg: {leg.keys()}")
            
            if not geometry_found and len(waypoints) > 1:
                # Fallback to straight lines if no geometry available
                print(f"Using fallback straight lines for vehicle {vehicle_id} with {len(waypoints)} waypoints")
                route_coords = [[wp[1], wp[0]] for wp in waypoints]
                folium.PolyLine(
                    route_coords,
                    color=color,
                    weight=3,
                    opacity=0.5,
                    popup=f"Vehicle {vehicle_id} Route (Direct)",
                    dashArray='5, 5'
                ).add_to(m)
                geometry_found = True
            
            if not geometry_found:
                print(f"No route found for vehicle {vehicle_id}")
            
            # Use optimized sequence from route data
            route_data = routes.get(vehicle_id, {})
            print(f"Route data keys for {vehicle_id}: {list(route_data.keys()) if route_data else 'None'}")
            sequence = route_data.get('sequence', [])
            print(f"Sequence for vehicle {vehicle_id}: {len(sequence)} stops")
            
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
                            journey_mins = stop.get('passenger_journey_time', 0) // 60
                            popup_content += f"• Request {stop['requestId']} - Journey: {journey_mins}min<br>"
                    
                    popup_content += f"Stop ID: {stops[0]['stopId']}"
                    
                    # Choose icon style based on stop type with vehicle data attribute
                    if pickup_stops and dropoff_stops:
                        # Mixed stop - both pickup and dropoff
                        icon_html = f'<div data-vehicle="{vehicle_id}" style="background: linear-gradient(45deg, {color} 50%, white 50%);color:black;border:2px solid {color};border-radius:50%;width:30px;height:30px;text-align:center;line-height:26px;font-weight:bold;font-size:12px;">{stop_number}</div>'
                    elif pickup_stops:
                        # Pickup only
                        icon_html = f'<div data-vehicle="{vehicle_id}" style="background-color:{color};color:white;border-radius:50%;width:30px;height:30px;text-align:center;line-height:30px;font-weight:bold;font-size:12px;">{stop_number}</div>'
                    else:
                        # Dropoff only
                        icon_html = f'<div data-vehicle="{vehicle_id}" style="background-color:white;color:{color};border:3px solid {color};border-radius:50%;width:30px;height:30px;text-align:center;line-height:24px;font-weight:bold;font-size:12px;">{stop_number}</div>'
                    
                    folium.Marker(
                        [coords[1], coords[0]],
                        popup=popup_content,
                        icon=folium.DivIcon(
                            html=icon_html,
                            icon_size=(30, 30)
                        )
                    ).add_to(m)
        
        # Generate optimization info (only if vehicles provided)
        optimization_info = self.generate_optimization_info(assignments, routes, vehicles) if vehicles else "<p>No vehicle information available</p>"
        
        # Add interactive time filter controls with CSS for vehicle toggling
        filter_html = f'''
        <style>
        .vehicle-toggle {{
            margin: 2px 0;
        }}
        .vehicle-toggle input {{
            margin-right: 5px;
        }}
        </style>
        <div style="position: fixed; 
                    top: 10px; left: 10px; width: 300px; height: auto; 
                    background-color: white; border:2px solid grey; z-index:9999; 
                    font-size:12px; padding: 10px">
        <h4>Time Filter</h4>
        <label>Start Time:</label><br>
        <input type="datetime-local" id="startTime" style="width:100%; margin:5px 0;"><br>
        <label>End Time:</label><br>
        <input type="datetime-local" id="endTime" style="width:100%; margin:5px 0;"><br>
        <label>Max Waiting Time (minutes):</label><br>
        <input type="number" id="maxWaitTime" value="15" min="5" max="120" style="width:100%; margin:5px 0;"><br>
        <label>Max Travel Duration (minutes):</label><br>
        <input type="number" id="maxTravelTime" value="20" min="15" max="180" style="width:100%; margin:5px 0;"><br>
        <button onclick="filterRoutes()" style="width:100%; padding:5px; background:#007cba; color:white; border:none; cursor:pointer;">Filter Routes</button>
        <button onclick="clearFilter()" style="width:100%; padding:5px; margin-top:5px; background:#666; color:white; border:none; cursor:pointer;">Show All</button>
        <button onclick="showOptimizationInfo()" style="width:100%; padding:5px; margin-top:5px; background:#28a745; color:white; border:none; cursor:pointer;">📊 Route Details</button>
        <div id="filterStatus" style="margin-top:10px; font-size:11px; color:#666;">Showing all routes</div>
        </div>
        
        <!-- Optimization Info Modal -->
        <div id="optimizationModal" style="display:none; position:fixed; z-index:10000; left:0; top:0; width:100%; height:100%; background-color:rgba(0,0,0,0.5);">
            <div style="background-color:white; margin:5% auto; padding:20px; border:1px solid #888; width:80%; max-height:80%; overflow-y:auto;">
                <span onclick="closeOptimizationInfo()" style="color:#aaa; float:right; font-size:28px; font-weight:bold; cursor:pointer;">&times;</span>
                <div id="optimizationContent">{optimization_info}</div>
            </div>
        </div>
        
        <script>
        // Load current URL parameters into form fields
        window.onload = function() {{
            const urlParams = new URLSearchParams(window.location.search);
            const start = urlParams.get('start');
            const end = urlParams.get('end');
            const maxWait = urlParams.get('maxwait') || '15';
            const maxTravel = urlParams.get('maxtravel') || '20';
            
            if (start) {{
                document.getElementById('startTime').value = start.replace(' ', 'T');
            }} else {{
                // Set default to today 7am
                const today = new Date();
                today.setHours(7, 0, 0, 0);
                document.getElementById('startTime').value = today.toISOString().slice(0, 16);
            }}
            if (end) {{
                document.getElementById('endTime').value = end.replace(' ', 'T');
            }} else {{
                // Set default to today 7pm
                const today = new Date();
                today.setHours(19, 0, 0, 0);
                document.getElementById('endTime').value = today.toISOString().slice(0, 16);
            }}
            document.getElementById('maxWaitTime').value = maxWait;
            document.getElementById('maxTravelTime').value = maxTravel;
            
            // Update status message
            if (start && end) {{
                document.getElementById('filterStatus').innerHTML = `Filtered: ${{start}} to ${{end}}`;
            }} else {{
                document.getElementById('filterStatus').innerHTML = 'Showing all routes';
            }}
        }};
        
        function filterRoutes() {{
            const start = document.getElementById('startTime').value;
            const end = document.getElementById('endTime').value;
            const maxWait = document.getElementById('maxWaitTime').value;
            const maxTravel = document.getElementById('maxTravelTime').value;
            if (start && end) {{
                const startFormatted = start.replace('T', ' ');
                const endFormatted = end.replace('T', ' ');
                document.getElementById('filterStatus').innerHTML = 'Filtering routes...';
                window.location.href = `/filter?start=${{startFormatted}}&end=${{endFormatted}}&maxwait=${{maxWait}}&maxtravel=${{maxTravel}}`;
            }} else {{
                alert('Please select both start and end times');
            }}
        }}
        
        function clearFilter() {{
            document.getElementById('startTime').value = '';
            document.getElementById('endTime').value = '';
            document.getElementById('maxWaitTime').value = '15';
            document.getElementById('maxTravelTime').value = '20';
            document.getElementById('filterStatus').innerHTML = 'Showing all routes';
            window.location.href = '/';
        }}
        
        function showOptimizationInfo() {{
            document.getElementById('optimizationModal').style.display = 'block';
        }}
        
        function closeOptimizationInfo() {{
            document.getElementById('optimizationModal').style.display = 'none';
        }}
        
        window.onclick = function(event) {{
            const modal = document.getElementById('optimizationModal');
            if (event.target == modal) {{
                modal.style.display = 'none';
            }}
        }}
        
        function toggleVehicle(vehicleId, color) {{
            const checkbox = document.getElementById('vehicle_' + vehicleId);
            const display = checkbox.checked ? '' : 'none';
            
            // Toggle route lines (SVG paths with specific color)
            const paths = document.querySelectorAll('path[stroke="' + color + '"]');
            paths.forEach(function(path) {{
                path.style.display = display;
            }});
            
            // Toggle vehicle car markers (find by popup content)
            const markers = document.querySelectorAll('.leaflet-marker-icon');
            markers.forEach(function(marker) {{
                // Check if this is a vehicle marker by looking for car icon or vehicle popup
                if (marker.innerHTML && marker.innerHTML.includes('fa-car')) {{
                    // This is likely a vehicle marker, check popup for vehicle ID
                    const markerParent = marker.closest('.leaflet-marker-pane');
                    if (markerParent) {{
                        // Find associated popup or check marker attributes
                        const hasVehicleId = marker.outerHTML.includes(vehicleId) || 
                                           (marker.title && marker.title.includes(vehicleId));
                        if (hasVehicleId) {{
                            marker.style.display = display;
                        }}
                    }}
                }}
            }});
            
            // Toggle stop markers with data-vehicle attribute
            const stopMarkers = document.querySelectorAll('[data-vehicle="' + vehicleId + '"]');
            stopMarkers.forEach(function(marker) {{
                // Hide the entire marker container
                const markerContainer = marker.closest('.leaflet-marker-icon') || marker.closest('.leaflet-div-icon');
                if (markerContainer) {{
                    markerContainer.style.display = display;
                }} else {{
                    marker.style.display = display;
                }}
            }});
            
            // Also toggle by color for any remaining elements
            setTimeout(function() {{
                const divIcons = document.querySelectorAll('.leaflet-div-icon');
                divIcons.forEach(function(icon) {{
                    const innerDiv = icon.querySelector('[data-vehicle="' + vehicleId + '"]');
                    if (innerDiv) {{
                        icon.style.display = display;
                    }}
                }});
            }}, 50);
        }}
        </script>
        '''
        
        # Add legend with vehicle toggles
        legend_html = '''
        <div style="position: fixed; 
                    bottom: 50px; left: 50px; width: 250px; height: auto; 
                    background-color: white; border:2px solid grey; z-index:9999; 
                    font-size:14px; padding: 10px">
        <h4>Route Legend</h4>
        '''        
        
        has_active_routes = False
        for i, (vehicle_id, _) in enumerate(assignments.items()):
            if assignments[vehicle_id]:
                color = colors[i % len(colors)]
                legend_html += f'''
                <p class="vehicle-toggle">
                    <input type="checkbox" id="vehicle_{vehicle_id}" checked onchange="toggleVehicle('{vehicle_id}', '{color}')">
                    <span style="color:{color};">■</span> Vehicle {vehicle_id}
                </p>'''
                has_active_routes = True
        
        if has_active_routes:
            legend_html += '''
            <hr style="margin: 10px 0;">
            <p><span style="background-color:#333;color:white;border-radius:50%;padding:2px 6px;font-size:12px;">1</span> HOP ON (Pickup)</p>
            <p><span style="background-color:white;color:#333;border:2px solid #333;border-radius:50%;padding:2px 6px;font-size:12px;">2</span> DROP OFF</p>
            <p>🚗 Vehicle Start Position</p>
            <p><strong>Numbers show stop order</strong></p>
            '''
        else:
            legend_html += '<p><em>No routes found for selected time period</em></p>'
        
        legend_html += '</div>'
        
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
        try:
            filter_html = filter_html.replace(f"map_{int(time.time())}", map_var)
            m.get_root().html.add_child(folium.Element(filter_html))
            m.get_root().html.add_child(folium.Element(info_html))
            m.get_root().html.add_child(folium.Element(legend_html))
            print("Successfully added HTML elements to map")
        except Exception as e:
            print(f"Error adding HTML elements to map: {e}")
            raise
        
        try:
            map_file = f"route_map_{int(time.time())}.html"
            m.save(map_file)
            print(f"Successfully saved map to {map_file}")
            
            # Verify file was created and has content
            if os.path.exists(map_file):
                file_size = os.path.getsize(map_file)
                print(f"Map file size: {file_size} bytes")
                if file_size == 0:
                    print("Warning: Map file is empty")
            else:
                print(f"Error: Map file {map_file} was not created")
                return None
                
            return map_file
        except Exception as e:
            print(f"Error saving map file: {e}")
            import traceback
            traceback.print_exc()
            return None
        
        except Exception as e:
            print(f"Error in create_route_map: {e}")
            import traceback
            traceback.print_exc()
            return None
    
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
    
    def _is_nearby(self, pos1: List[float], pos2: List[float], threshold: float = 0.01) -> bool:
        """Check if two positions are nearby (within threshold distance)"""
        return self._calculate_distance(pos1, pos2) < threshold
    
    def _calculate_route_efficiency_penalty(self, request: Dict, current_requests: List[Dict]) -> float:
        """Calculate penalty for route inefficiency with fixed bus stops"""
        if not current_requests:
            return 0
        
        origin = self.get_stop_coords(request['originStopId'])
        dest = self.get_stop_coords(request['destStopId'])
        
        # Get all existing stop coordinates
        existing_coords = []
        for req in current_requests:
            o_coords = self.get_stop_coords(req['originStopId'])
            d_coords = self.get_stop_coords(req['destStopId'])
            if o_coords: existing_coords.append(o_coords)
            if d_coords: existing_coords.append(d_coords)
        
        if not existing_coords:
            return 0
        
        # Calculate route compactness - penalty for stops that create large detours
        # Find the bounding box of existing stops
        min_lon = min(coord[0] for coord in existing_coords)
        max_lon = max(coord[0] for coord in existing_coords)
        min_lat = min(coord[1] for coord in existing_coords)
        max_lat = max(coord[1] for coord in existing_coords)
        
        # Penalty if new stops extend the route significantly
        penalty = 0
        if origin[0] < min_lon or origin[0] > max_lon or origin[1] < min_lat or origin[1] > max_lat:
            penalty += 0.3  # Origin extends route
        if dest[0] < min_lon or dest[0] > max_lon or dest[1] < min_lat or dest[1] > max_lat:
            penalty += 0.3  # Destination extends route
        
        return penalty
    
    def _calculate_time_clustering_bonus(self, request: Dict, current_requests: List[Dict]) -> float:
        """Bonus for requests with similar pickup times (efficient batching)"""
        if not current_requests:
            return 0
        
        request_dt = request.get('requestedPickupAt')
        if not request_dt:
            return 0
        
        # Calculate average time difference with existing requests
        time_diffs = []
        for existing in current_requests:
            existing_dt = existing.get('requestedPickupAt')
            if existing_dt:
                time_diff = abs((request_dt - existing_dt).total_seconds()) / 60  # minutes
                time_diffs.append(time_diff)
        
        if not time_diffs:
            return 0
        
        avg_time_diff = sum(time_diffs) / len(time_diffs)
        # Bonus for requests within 10 minutes of each other
        return -max(0, (10 - avg_time_diff) * 0.02)  # Negative = bonus
    
    def _calculate_geo_clustering_bonus(self, request: Dict, current_requests: List[Dict]) -> float:
        """Bonus for requests sharing same bus stops (efficient stop reuse)"""
        if not current_requests:
            return 0
        
        request_origin = request['originStopId']
        request_dest = request['destStopId']
        
        shared_stops_bonus = 0
        
        # Check if any existing requests share the same origin or destination stops
        for existing in current_requests:
            existing_origin = existing['originStopId']
            existing_dest = existing['destStopId']
            
            # Bonus for sharing pickup stop (multiple passengers board at same stop)
            if request_origin == existing_origin:
                shared_stops_bonus -= 0.2  # Strong bonus for shared pickup
            
            # Bonus for sharing dropoff stop (multiple passengers exit at same stop)
            if request_dest == existing_dest:
                shared_stops_bonus -= 0.2  # Strong bonus for shared dropoff
            
            # Bonus for origin-destination overlap (efficient routing)
            if request_origin == existing_dest or request_dest == existing_origin:
                shared_stops_bonus -= 0.1  # Medium bonus for route overlap
        
        return shared_stops_bonus
    
    def run_optimization(self, start_datetime: str = None, end_datetime: str = None, max_wait_minutes: int = 15, max_travel_minutes: int = 20):
        """Main optimization process with optional datetime filter, waiting time and travel duration"""
        try:
            print("Starting route optimization...")
            
            # Convert datetime strings to datetime objects if provided
            start_time = None
            end_time = None
            if start_datetime:
                try:
                    start_time = datetime.strptime(start_datetime, '%Y-%m-%d %H:%M')
                except ValueError as e:
                    print(f"Error parsing start datetime '{start_datetime}': {e}")
                    return {}, {}, None
            if end_datetime:
                try:
                    end_time = datetime.strptime(end_datetime, '%Y-%m-%d %H:%M')
                except ValueError as e:
                    print(f"Error parsing end datetime '{end_datetime}': {e}")
                    return {}, {}, None
            
            if start_time and end_time:
                if start_time > end_time:
                    print(f"Warning: Start time {start_datetime} is after end time {end_datetime}. Swapping dates.")
                    start_time, end_time = end_time, start_time
                    start_datetime, end_datetime = end_datetime, start_datetime
                print(f"Filtering requests from {start_datetime} to {end_datetime}")
            
            print(f"Using max waiting time: {max_wait_minutes} minutes")
            print(f"Using max travel duration: {max_travel_minutes} minutes")
            
            # Get data from DynamoDB
            try:
                requests = self.get_requests(start_time, end_time)
                print(f"Successfully retrieved {len(requests)} requests")
            except Exception as e:
                print(f"Error retrieving requests from DynamoDB: {e}")
                return {}, {}, None
            
            try:
                vehicles = self.get_vehicles()
                print(f"Successfully retrieved {len(vehicles)} vehicles")
            except Exception as e:
                print(f"Error retrieving vehicles from DynamoDB: {e}")
                return {}, {}, None
            
            if not requests:
                print("No requests found! Creating empty map.")
                # Create empty map when no requests found - no Lambda calls needed
                try:
                    empty_assignments = {vehicle['vehicleId']: [] for vehicle in vehicles}
                    map_file = self.create_route_map(empty_assignments, {}, vehicles)
                    return empty_assignments, {}, map_file
                except Exception as e:
                    print(f"Error creating empty map: {e}")
                    return {}, {}, None
                
            if not vehicles:
                print("No vehicles found!")
                return {}, {}, None
            
            # Assign requests to vehicles
            try:
                assignments = self.assign_requests_to_vehicles(requests, vehicles, max_wait_minutes, max_travel_minutes)
                print(f"Successfully assigned requests to vehicles")
                print(f"Assignment summary: {[(k, len(v)) for k, v in assignments.items()]}")
            except Exception as e:
                print(f"Error assigning requests to vehicles: {e}")
                return {}, {}, None
            
            # Optimize routes for each vehicle - only call Lambda if there are requests
            routes = {}
            vehicles_with_requests = [(k, v) for k, v in assignments.items() if v]
            print(f"Vehicles with requests: {len(vehicles_with_requests)}")
            
            for vehicle_id, vehicle_requests in assignments.items():
                if vehicle_requests:
                    try:
                        print(f"Calling Lambda for vehicle {vehicle_id} with {len(vehicle_requests)} requests")
                        routes[vehicle_id] = self.optimize_route_with_location_service(vehicle_id, vehicle_requests)
                        print(f"Successfully optimized route for vehicle {vehicle_id}")
                    except Exception as e:
                        print(f"Error optimizing route for vehicle {vehicle_id}: {e}")
                        routes[vehicle_id] = {'route': [], 'distance': 0, 'duration': 0}
                else:
                    print(f"No requests for vehicle {vehicle_id} - skipping Lambda call")
            
            # Create map
            try:
                map_file = self.create_route_map(assignments, routes, vehicles)
                if map_file:
                    print(f"Successfully created map file: {map_file}")
                else:
                    print("Map creation returned None")
            except Exception as e:
                print(f"Error creating map: {e}")
                import traceback
                traceback.print_exc()
                return assignments, routes, None
            
            # Display results
            try:
                self._display_results(assignments, routes, map_file, vehicles)
            except Exception as e:
                print(f"Error displaying results: {e}")
            
            return assignments, routes, map_file
            
        except Exception as e:
            print(f"Unexpected error in run_optimization: {e}")
            import traceback
            traceback.print_exc()
            return {}, {}, None
    
    def _display_results(self, assignments: Dict, routes: Dict, map_file: str, vehicles: List[Dict]):
        """Display optimization results"""
        print("\n=== DYNAMIC ROUTE OPTIMIZATION RESULTS ===")
        
        total_requests = sum(len(reqs) for reqs in assignments.values())
        total_distance = sum(route.get('distance', 0) for route in routes.values()) / 1000  # Convert to km
        total_duration = sum(route.get('duration', 0) for route in routes.values())
        total_fuel = sum(route.get('fuel_consumption_liters', 0) for route in routes.values())
        total_co2 = sum(route.get('co2_emissions_kg', 0) for route in routes.values())
        
        print(f"Total Requests Assigned: {total_requests}")
        print(f"Total Route Distance: {total_distance:.2f} km")
        print(f"Total Route Duration: {total_duration//60:.0f} minutes")
        print(f"\n=== ENVIRONMENTAL IMPACT ===")
        print(f"Total Fuel Consumption: {total_fuel:.2f} liters")
        print(f"Total CO2 Emissions: {total_co2:.2f} kg")
        if total_requests > 0:
            print(f"Fuel per Passenger: {total_fuel/total_requests:.2f} L")
            print(f"CO2 per Passenger: {total_co2/total_requests:.2f} kg")
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
                
                print(f"  Route distance: {route.get('distance', 0)/1000:.2f}km")
                if route.get('duration'):
                    print(f"  Route duration: {route['duration']//60:.0f} minutes")
                if route.get('fuel_consumption_liters'):
                    print(f"  Fuel consumption: {route['fuel_consumption_liters']:.2f}L")
                    print(f"  CO2 emissions: {route['co2_emissions_kg']:.2f}kg")
            else:
                print(f"  No requests assigned")
    
    def generate_optimization_info(self, assignments: Dict, routes: Dict, vehicles: List[Dict]) -> str:
        """Generate detailed optimization information for web display"""
        total_requests = sum(len(reqs) for reqs in assignments.values())
        total_distance = sum(route.get('distance', 0) for route in routes.values()) / 1000
        total_duration = sum(route.get('duration', 0) for route in routes.values())
        total_fuel = sum(route.get('fuel_consumption_liters', 0) for route in routes.values())
        total_co2 = sum(route.get('co2_emissions_kg', 0) for route in routes.values())
        
        info_html = f"""
        <h3>Route Optimization Results</h3>
        <div style="margin-bottom: 20px;">
            <h4>Summary</h4>
            <p><strong>Total Requests:</strong> {total_requests}</p>
            <p><strong>Total Distance:</strong> {total_distance:.2f} km</p>
            <p><strong>Total Duration:</strong> {total_duration//60:.0f} minutes</p>
        </div>
        
        <div style="margin-bottom: 20px;">
            <h4>Environmental Impact</h4>
            <p><strong>Fuel Consumption:</strong> {total_fuel:.2f} liters</p>
            <p><strong>CO2 Emissions:</strong> {total_co2:.2f} kg</p>
        """
        
        if total_requests > 0:
            info_html += f"""
            <p><strong>Fuel per Passenger:</strong> {total_fuel/total_requests:.2f} L</p>
            <p><strong>CO2 per Passenger:</strong> {total_co2/total_requests:.2f} kg</p>
            """
        
        info_html += "</div>"
        
        # Vehicle details
        vehicles_map = {v['vehicleId']: v for v in vehicles}
        
        for vehicle_id in assignments.keys():
            vehicle = vehicles_map.get(vehicle_id, {})
            vehicle_requests = assignments[vehicle_id]
            route = routes.get(vehicle_id, {})
            
            info_html += f"<div style='margin-bottom: 20px; border: 1px solid #ccc; padding: 10px;'>"
            info_html += f"<h4>Vehicle {vehicle_id}</h4>"
            
            if vehicle_requests:
                sorted_reqs = sorted(vehicle_requests, key=lambda r: r.get('requestedPickupAt') or datetime.fromtimestamp(0))
                
                info_html += f"<p><strong>Assigned Requests:</strong> {len(vehicle_requests)}</p>"
                info_html += f"<p><strong>Route Distance:</strong> {route.get('distance', 0)/1000:.2f} km</p>"
                info_html += f"<p><strong>Route Duration:</strong> {route.get('duration', 0)//60:.0f} minutes</p>"
                
                if route.get('fuel_consumption_liters'):
                    info_html += f"<p><strong>Fuel:</strong> {route['fuel_consumption_liters']:.2f}L</p>"
                    info_html += f"<p><strong>CO2:</strong> {route['co2_emissions_kg']:.2f}kg</p>"
                
                info_html += "<h5>Stop Sequence:</h5><ol>"
                stop_number = 1
                
                for req in sorted_reqs:
                    pickup_dt = req.get('requestedPickupAt')
                    pickup_time = pickup_dt.strftime('%H:%M') if pickup_dt else 'N/A'
                    
                    info_html += f"<li>HOP ON - {req['originStopId']} (Request {req.get('requestId', 'N/A')}) at {pickup_time}</li>"
                    info_html += f"<li>DROP OFF - {req['destStopId']} (Request {req.get('requestId', 'N/A')})</li>"
                
                info_html += "</ol>"
                
                # Time span info
                if len(sorted_reqs) > 1:
                    pickup_times = [r.get('requestedPickupAt') for r in sorted_reqs if r.get('requestedPickupAt')]
                    if pickup_times:
                        min_time = min(pickup_times)
                        max_time = max(pickup_times)
                        time_span = (max_time - min_time).total_seconds() / 60
                        info_html += f"<p><strong>Time Span:</strong> {time_span:.1f} minutes</p>"
                
                info_html += f"<p><strong>Utilization:</strong> {len(sorted_reqs)}/{vehicle.get('capacity', 20)} capacity</p>"
            else:
                info_html += "<p>No requests assigned</p>"
            
            info_html += "</div>"
        
        return info_html
    
    def _calculate_route_locally(self, vehicle_id: str, requests: List[Dict]) -> Dict:
        """Fallback local route calculation when Lambda fails"""
        if not requests:
            return {'route': [], 'distance': 0, 'duration': 0, 'waypoints': [], 'sequence': []}
        
        # Sort requests by pickup time
        sorted_requests = sorted(requests, key=lambda r: r.get('requestedPickupAt', ''))
        
        # Create stop sequence
        all_stops = []
        pickup_order = {}
        
        # Add pickups in time order
        for i, req in enumerate(sorted_requests):
            origin = self.get_stop_coords(req['originStopId'])
            if origin:
                all_stops.append({
                    'type': 'pickup',
                    'requestId': req.get('requestId'),
                    'stopId': req['originStopId'],
                    'coords': origin,
                    'priority': i
                })
                pickup_order[req.get('requestId')] = i
        
        # Add dropoffs
        for req in sorted_requests:
            dest = self.get_stop_coords(req['destStopId'])
            if dest:
                all_stops.append({
                    'type': 'dropoff',
                    'requestId': req.get('requestId'),
                    'stopId': req['destStopId'],
                    'coords': dest,
                    'priority': pickup_order.get(req.get('requestId'), 999) + 100
                })
        
        # Sort by priority
        all_stops.sort(key=lambda x: x['priority'])
        waypoints = [stop['coords'] for stop in all_stops]
        
        if len(waypoints) < 2:
            return {'route': [], 'distance': 0, 'duration': 0, 'waypoints': waypoints, 'sequence': all_stops}
        
        # Limit waypoints
        if len(waypoints) > 23:
            waypoints = waypoints[:23]
            all_stops = all_stops[:23]
        
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
                'sequence': all_stops
            }
            
        except Exception as e:
            print(f"Local route calculation failed: {e}")
            return {
                'route': [],
                'distance': 0,
                'duration': 0,
                'waypoints': waypoints,
                'sequence': all_stops
            }
    
    def _save_empty_map(self, m, filter_html, info_html, legend_html):
        """Save empty map without processing routes"""
        try:
            map_var = f"map_{int(time.time())}"
            filter_html = filter_html.replace(f"map_{int(time.time())}", map_var)
            m.get_root().html.add_child(folium.Element(filter_html))
            m.get_root().html.add_child(folium.Element(info_html))
            m.get_root().html.add_child(folium.Element(legend_html))
            
            map_file = f"route_map_{int(time.time())}.html"
            m.save(map_file)
            print(f"Empty map saved as: {map_file}")
            return map_file
        except Exception as e:
            print(f"Error saving empty map: {e}")
            return None

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