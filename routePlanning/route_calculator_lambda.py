import boto3
import json
from datetime import datetime
from typing import List, Dict, Any

def lambda_handler(event, context):
    """Lambda function to calculate optimized routes for vehicles"""
    try:
        # Parse input
        vehicle_id = event.get('vehicle_id')
        requests = event.get('requests', [])
        
        if not vehicle_id or not requests:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'vehicle_id and requests are required'})
            }
        
        # Initialize route calculator
        calculator = RouteCalculator()
        
        # Calculate optimized route
        route_result = calculator.optimize_route(vehicle_id, requests)
        
        return {
            'statusCode': 200,
            'body': json.dumps(route_result, default=str)
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }

class RouteCalculator:
    def __init__(self):
        self.dynamodb = boto3.resource('dynamodb')
        self.stops_table = self.dynamodb.Table('stops')
        self.location_client = boto3.client('location')
        self.map_name = 'leiria-map'
    
    def get_stop_coords(self, stop_id: str) -> List[float]:
        """Get coordinates for a stop"""
        try:
            response = self.stops_table.get_item(Key={'stop_id': stop_id})
            if 'Item' in response:
                item = response['Item']
                return [float(item['stop_lon']), float(item['stop_lat'])]
        except Exception as e:
            print(f"Error getting stop coords for {stop_id}: {e}")
        return None
    
    def optimize_route(self, vehicle_id: str, requests: List[Dict]) -> Dict:
        """Calculate optimized route for vehicle with given requests"""
        if not requests:
            return {'route': [], 'distance': 0, 'duration': 0}
        
        # Sort requests by pickup time
        sorted_requests = sorted(requests, key=lambda r: r.get('requestedPickupAt', ''))
        
        # Create stop sequence
        all_stops = []
        pickup_order = {}
        
        # Add pickups in time order
        for i, req in enumerate(sorted_requests):
            origin = self.get_stop_coords(req['originStopId'])
            if origin:
                pickup_stop = {
                    'type': 'pickup',
                    'requestId': req.get('requestId'),
                    'stopId': req['originStopId'],
                    'coords': origin,
                    'priority': i
                }
                all_stops.append(pickup_stop)
                pickup_order[req.get('requestId')] = i
        
        # Add dropoffs
        for req in sorted_requests:
            dest = self.get_stop_coords(req['destStopId'])
            if dest:
                dropoff_stop = {
                    'type': 'dropoff',
                    'requestId': req.get('requestId'),
                    'stopId': req['destStopId'],
                    'coords': dest,
                    'priority': pickup_order.get(req.get('requestId'), 999) + 100
                }
                all_stops.append(dropoff_stop)
        
        # Sort by priority
        all_stops.sort(key=lambda x: x['priority'])
        waypoints = [stop['coords'] for stop in all_stops]
        
        if len(waypoints) < 2:
            return {'route': [], 'distance': 0, 'duration': 0}
        
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
            print(f"Route calculation failed: {e}")
            return {
                'route': [], 
                'distance': 0, 
                'duration': 0, 
                'waypoints': waypoints, 
                'sequence': all_stops
            }