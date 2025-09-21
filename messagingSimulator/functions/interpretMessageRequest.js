import { BedrockRuntimeClient, InvokeModelCommand } from "@aws-sdk/client-bedrock-runtime";
import { DynamoDBClient, ScanCommand, PutItemCommand } from "@aws-sdk/client-dynamodb";

const bedrockClient = new BedrockRuntimeClient({ region: process.env.AWS_REGION || 'us-east-1' });

export const handler = async (event) => {
  try {
    console.log("Incoming event:", JSON.stringify(event));

    if (event.requestContext?.http?.method === 'OPTIONS' || event.httpMethod === 'OPTIONS') {
      return {
        statusCode: 200,
        body: '',
      };
    }

    const body = JSON.parse(event.body || "{}");
    const message = body.message;
    const sessionId = body.sessionId || `session-${Date.now()}`;

    if (!message) {
      return {
        statusCode: 400,
        body: JSON.stringify({ error: 'Message is required' }),
      };
    }

    // Get current datetime for fallback
    const now = new Date();
    const currentDate = now.toISOString().split('T')[0]; // YYYY-MM-DD
    const currentTime = now.toTimeString().split(' ')[0].slice(0, 5); // HH:MM



    // Bedrock prompt for bus booking extraction in Leiria context
    const prompt = `Extract bus booking information from this user message in Leiria, Portugal context and return ONLY a valid JSON object.

User message: "${message}"

Extract these fields (use null if truly not mentioned):
- origin: departure location (look for "from", "de", starting point, or null if not specified)
- destination: arrival location (look for "to", "para", "até", ending point, or null if not specified)  
- time: departure time (extract if mentioned, or null if not specified)
- date: travel date (extract if mentioned, or "${currentDate}" as default)

Context: This is for bus transportation in Leiria, Portugal. Common locations include:
- Centro (city center)
- Estação (train station)
- Hospital
- Universidade (university)
- Castelo (castle)
- Mercado (market)
- Street names (Rua, Avenida)
- Shops, restaurants, landmarks

Return only the JSON object, no other text:`;

    const command = new InvokeModelCommand({
      modelId: "anthropic.claude-3-haiku-20240307-v1:0",
      body: JSON.stringify({
        anthropic_version: "bedrock-2023-05-31",
        max_tokens: 200,
        messages: [{ role: "user", content: prompt }]
      }),
      contentType: "application/json",
      accept: "application/json"
    });

    console.log("Sending Bedrock command...");
    const response = await bedrockClient.send(command);
    console.log("Bedrock command sent successfully");
    
    const responseBody = JSON.parse(new TextDecoder().decode(response.body));
    console.log("Bedrock response:", responseBody);

    // Parse Claude's response
    let parsedData;
    try {
      const content = responseBody.content[0].text;
      const jsonMatch = content.match(/\{[\s\S]*\}/);
      if (jsonMatch) {
        parsedData = JSON.parse(jsonMatch[0]);
      } else {
        throw new Error("No JSON found in response");
      }
    } catch (err) {
      console.error("Failed to parse Bedrock response:", err);
      parsedData = { 
        origin: "Centro", 
        destination: "Estação", 
        time: currentTime, 
        date: currentDate 
      };
    }


    
    // Check for missing information
    const missingOrigin = !parsedData.origin || parsedData.origin === "not specified" || parsedData.origin === null;
    const missingDestination = !parsedData.destination || parsedData.destination === "not specified" || parsedData.destination === null;
    const missingTime = !parsedData.time || parsedData.time === "not specified" || parsedData.time === null;
    
    // If critical information is missing, ask for it
    if (missingOrigin && missingDestination) {
      return {
        statusCode: 200,
        body: JSON.stringify({ 
          transcript: message, 
          lexResponse: { 
            parsedData: {},
            responseType: 'conversation',
            message: 'I need to know where you want to travel.\n\nPlease tell me:\n- Where are you starting from (origin)?\n- Where do you want to go (destination)?\n- What time do you need pickup?\n\nExample: "From Centro to Hospital at 15:30"'
          }
        }),
      };
    }
    
    if (missingOrigin) {
      return {
        statusCode: 200,
        body: JSON.stringify({ 
          transcript: message, 
          lexResponse: { 
            parsedData: { destination: parsedData.destination },
            responseType: 'conversation',
            message: `I see you want to go to ${parsedData.destination}. Where are you starting from?\n\nExample: "From Centro" or "From Piscinas Municipais"`
          }
        }),
      };
    }
    
    if (missingDestination) {
      return {
        statusCode: 200,
        body: JSON.stringify({ 
          transcript: message, 
          lexResponse: { 
            parsedData: { origin: parsedData.origin },
            responseType: 'conversation',
            message: `I see you're starting from ${parsedData.origin}. Where do you want to go?\n\nExample: "To Hospital" or "To Estação"`
          }
        }),
      };
    }
    
    // Set defaults for non-null values
    if (!parsedData.time || parsedData.time === "not specified" || parsedData.time === null) {
      parsedData.time = currentTime;
    }
    if (!parsedData.date || parsedData.date === "not specified" || parsedData.date === null) {
      parsedData.date = currentDate;
    }

    console.log("Final parsed data:", parsedData);

    const dynamoClient = new DynamoDBClient({ region: process.env.AWS_REGION });

    // Function to save bus request to DynamoDB
    async function saveBusRequest(originStopId, destStopId, requestedPickupAt) {
      const requestId = `req_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      
      const putCommand = new PutItemCommand({
        TableName: "requests",
        Item: {
          requestId: { S: requestId },
          originStopId: { S: originStopId },
          destStopId: { S: destStopId },
          requestedPickupAt: { S: requestedPickupAt },
          assignedVehicleId: { NULL: true },
          isPMR: { S: "False" },
          isSenior: { S: "False" },
          status: { S: "False" }
        }
      });
      
      await dynamoClient.send(putCommand);
      console.log(`Bus request saved with ID: ${requestId}`);
      
      // Trigger route recalculation
      try {
        const { spawn } = require('child_process');
        const python = spawn('python', ['../routePlanning/dynamic_route_optimizer.py', 'recalculate']);
        
        python.stdout.on('data', (data) => {
          console.log('Route optimizer output:', data.toString());
        });
        
        python.stderr.on('data', (data) => {
          console.error('Route optimizer error:', data.toString());
        });
        
        console.log('Route recalculation triggered');
      } catch (err) {
        console.error('Failed to trigger route recalculation:', err.message);
      }
      return requestId;
    }

    // Get all bus stops from DynamoDB
    console.log("Fetching bus stops from DynamoDB...");
    const stopsResp = await dynamoClient.send(new ScanCommand({
      TableName: "stops"
    }));
    console.log(`Retrieved ${stopsResp.Items.length} bus stops`);

    // Function to calculate direction based on coordinates using Leiria landmarks
    function calculateDirection(lat, lon) {
      const centerLat = 39.7491; // Leiria city center
      const centerLon = -8.8118;
      
      const deltaLat = lat - centerLat;
      const deltaLon = lon - centerLon;
      
      // Calculate angle in degrees
      const angle = Math.atan2(deltaLat, deltaLon) * 180 / Math.PI;
      
      // Convert to Leiria landmark directions
      if (angle >= -22.5 && angle < 22.5) return "→ Dir. Marrazes";
      if (angle >= 22.5 && angle < 67.5) return "↗ Dir. Castelo";
      if (angle >= 67.5 && angle < 112.5) return "↑ Dir. Castelo";
      if (angle >= 112.5 && angle < 157.5) return "↖ Dir. Pousos";
      if (angle >= 157.5 || angle < -157.5) return "← Dir. Pousos";
      if (angle >= -157.5 && angle < -112.5) return "↙ Dir. Estação";
      if (angle >= -112.5 && angle < -67.5) return "↓ Dir. Estação";
      if (angle >= -67.5 && angle < -22.5) return "↘ Dir. Hospital";
      return "📍 Centro";
    }

    const busStops = stopsResp.Items.map(item => {
      const lat = parseFloat(item.stop_lat.S);
      const lon = parseFloat(item.stop_lon.S);
      return {
        stop_id: item.stop_id.S,
        name: item.stop_name?.S || item.stop_id.S,
        lat: lat,
        lon: lon,
        direction: calculateDirection(lat, lon)
      };
    });
    console.log("Bus stops processed:", busStops.length);

    // Use Bedrock AI to find nearest stations
    async function findNearestStationsWithAI(location, stops) {
      const stopsContext = stops.map(stop => 
        `${stop.name} (ID: ${stop.stop_id}) at coordinates ${stop.lat}, ${stop.lon}`
      ).join('\n');

      const nearestPrompt = `You are a local transportation expert for Leiria, Portugal. Find the nearest bus stops to: "${location}"

Available bus stops with coordinates:
${stopsContext}

Location Analysis Guide:
1. **Street Names** (Rua, Avenida, Largo, Praça):
   - Match stops on or very near that specific street
   - Consider cross streets and nearby intersections
   
2. **Shops/Restaurants/Businesses**:
   - Most commercial establishments are in city center (centro)
   - Popular restaurants/cafes typically near Praça Rodrigues Lobo
   - Shopping areas usually have multiple nearby stops
   
3. **Landmarks & Areas**:
   - Centro/City Center: central coordinates around 39.7491, -8.8118
   - Castelo de Leiria: elevated area, northern part of city
   - Hospital: typically has dedicated nearby stops
   - Estação (Train Station): major transport hub
   - Universidade: student area with good bus connections
   - Mercado Municipal: central market area

4. **Geographic Logic**:
   - Use coordinates to determine actual proximity
   - Consider Leiria's compact city layout
   - Streets in centro are walkable to multiple stops
   - Residential areas may have fewer but strategically placed stops

Matching Strategy:
- MUST return at least 1 stop, preferably 1-3 best matches
- Prioritize exact name matches first
- For streets: find stops with closest coordinates
- For businesses: assume city center location unless specified
- For landmarks: use known geographic positions
- If no clear match, return closest stops by coordinates
- Be generous but logical with matches

Return ONLY a JSON array (never empty):
[{"stop_id": "stop_001", "name": "Stop Name", "direction": "Direction"}]`;

      try {
        const nearestCommand = new InvokeModelCommand({
          modelId: "anthropic.claude-3-haiku-20240307-v1:0",
          body: JSON.stringify({
            anthropic_version: "bedrock-2023-05-31",
            max_tokens: 500,
            messages: [{ role: "user", content: nearestPrompt }]
          }),
          contentType: "application/json",
          accept: "application/json"
        });

        const nearestResponse = await bedrockClient.send(nearestCommand);
        const nearestBody = JSON.parse(new TextDecoder().decode(nearestResponse.body));
        
        const content = nearestBody.content[0].text;
        console.log(`AI response for location "${location}":`, content);
        
        const jsonMatch = content.match(/\[[\s\S]*\]/);
        
        if (jsonMatch) {
          const result = JSON.parse(jsonMatch[0]);
          console.log(`Parsed result for "${location}":`, result);
          return result;
        }
        
        console.log(`No JSON array found in AI response for "${location}", using fallback`);
        // Fallback: return closest stop by name similarity
        const fallbackStop = stops.find(stop => 
          stop.name.toLowerCase().includes(location.toLowerCase()) ||
          location.toLowerCase().includes(stop.name.toLowerCase())
        ) || stops[0];
        return [{ stop_id: fallbackStop.stop_id, name: fallbackStop.name, direction: fallbackStop.direction }];
        return [];
      } catch (err) {
        console.error("AI nearest station error:", err);
        console.error("Error details:", err.message);
        // Fallback: return closest stop by name or first available
        const fallbackStop = stops.find(stop => 
          stop.name.toLowerCase().includes(location.toLowerCase()) ||
          location.toLowerCase().includes(stop.name.toLowerCase())
        ) || stops[0];
        return [{ stop_id: fallbackStop.stop_id, name: fallbackStop.name, direction: fallbackStop.direction }];
      }
    }

    // Process origin and destination with error handling
    console.log(`Processing origin: "${parsedData.origin}" and destination: "${parsedData.destination}"`);
    let originStops = [];
    let destStops = [];
    
    try {
      console.log("Starting AI processing for locations...");
      [originStops, destStops] = await Promise.all([
        findNearestStationsWithAI(parsedData.origin, busStops),
        findNearestStationsWithAI(parsedData.destination, busStops)
      ]);
      console.log(`AI processing complete. Origin stops: ${originStops.length}, Dest stops: ${destStops.length}`);
    } catch (err) {
      console.error("Error processing locations:", err);
      console.error("Location processing error stack:", err.stack);
      // Fallback: use first available stops
      if (busStops.length >= 2) {
        originStops = [{ stop_id: busStops[0].stop_id, name: busStops[0].name, direction: busStops[0].direction }];
        destStops = [{ stop_id: busStops[1].stop_id, name: busStops[1].name, direction: busStops[1].direction }];
        console.log("Using fallback stops");
      }
    }

    // Function to handle duplicates and direction display
    function processStopsForDisplay(stops) {
      const nameGroups = {};
      
      // Group stops by name
      stops.forEach(stop => {
        if (!nameGroups[stop.name]) {
          nameGroups[stop.name] = [];
        }
        nameGroups[stop.name].push(stop);
      });
      
      const result = [];
      
      Object.entries(nameGroups).forEach(([name, group]) => {
        if (group.length === 1) {
          // Single stop - always include
          result.push({ ...group[0], showDirection: false });
        } else {
          // Multiple stops with same name
          const uniqueDirections = [...new Set(group.map(s => s.direction))];
          
          if (uniqueDirections.length > 1 && !uniqueDirections.some(d => !d || d.includes('Centro'))) {
            // Different valid directions - show all with directions
            group.forEach(stop => {
              result.push({ ...stop, showDirection: true });
            });
          } else {
            // Same direction or unclear directions - show only one
            result.push({ ...group[0], showDirection: false });
          }
        }
      });
      
      return result;
    }

    // Use AI to generate conversational responses
    async function generateConversationalResponse(situation, data) {
      const conversationPrompt = `You are QuickBus assistant for flexible bus service in Leiria, Portugal.

Situation: ${situation}
User's message: "${message}"
Data: ${JSON.stringify(data)}

For 'need_clarification' situation, include the clarificationText exactly as provided in the data.

Format your response in 2 parts:
1. Welcoming introduction explaining QuickBus flexible service (buses with adaptable routes, no fixed schedules, reduced waiting times)
2. Clear request for missing information

RULES (MANDATORY):
1. Respond in the SAME language the user used in their message
2. Always mention QuickBus flexible service benefits in introduction
3. Separate intro from request with line break
4. For situation 'need_pickup_time': ask for pickup time, mention found stops
5. For situation 'booking_confirmed': celebrate successful booking creation
6. For situation 'need_clarification': show the clarificationText with numbered options
7. Keep total response concise but informative
8. Be friendly and helpful

Generate only the response text:`;

      try {
        const conversationCommand = new InvokeModelCommand({
          modelId: "anthropic.claude-3-haiku-20240307-v1:0",
          body: JSON.stringify({
            anthropic_version: "bedrock-2023-05-31",
            max_tokens: 120,
            messages: [{ role: "user", content: conversationPrompt }]
          }),
          contentType: "application/json",
          accept: "application/json"
        });

        const conversationResponse = await bedrockClient.send(conversationCommand);
        const conversationBody = JSON.parse(new TextDecoder().decode(conversationResponse.body));
        return conversationBody.content[0].text.trim();
      } catch (err) {
        console.error("Conversation AI error:", err);
        return "I found some options for you. Please let me know your preferences.";
      }
    }

    // Determine response type
    let responseType = 'conversation';
    let responseMessage = '';

    if (originStops.length === 0 || destStops.length === 0) {
      responseMessage = await generateConversationalResponse('need_clearer_locations', { availableStops: busStops.slice(0, 10).map(s => s.name) });
    } else if (originStops.length === 1 && destStops.length === 1) {
      // Single match for both - check if time is provided
      const hasTime = parsedData.time && parsedData.time !== currentTime;
      
      if (hasTime) {
        // All data available - create request
        responseType = 'accepted';
        parsedData.originStopId = originStops[0].stop_id;
        parsedData.destStopId = destStops[0].stop_id;
        
        // Save to DynamoDB
        const timeToUse = parsedData.time && parsedData.time !== 'null' ? parsedData.time : currentTime;
        const requestedPickupAt = `${parsedData.date} ${timeToUse}:00`;
        await saveBusRequest(originStops[0].stop_id, destStops[0].stop_id, requestedPickupAt);
        
        responseMessage = `✅ Bus request created!\nFrom: ${originStops[0].name}\nTo: ${destStops[0].name}\nPickup: ${parsedData.time}`;
      } else {
        // Ask for pickup time
        responseMessage = await generateConversationalResponse('need_pickup_time', { 
          origin: originStops[0].name, 
          destination: destStops[0].name 
        });
      }
    } else {
      // Check if user provided exact matches that should create request
      const exactOriginMatch = originStops.find(stop => {
        const stopName = stop.name.toLowerCase();
        const userOrigin = parsedData.origin.toLowerCase();
        
        // Direct match or partial match (either direction)
        return stopName.includes(userOrigin) || 
               userOrigin.includes(stopName) ||
               // Handle common variations
               (stopName.includes('piscinas') && userOrigin.includes('piscinas')) ||
               (stopName.includes('estádio') && (userOrigin.includes('stadium') || userOrigin.includes('estadio'))) ||
               (stopName.includes('hospital') && userOrigin.includes('hospital')) ||
               (stopName.includes('centro') && userOrigin.includes('centro'));
      });
      
      const exactDestMatch = destStops.find(stop => {
        const stopName = stop.name.toLowerCase();
        const userDest = parsedData.destination.toLowerCase();
        
        // Direct match or partial match (either direction)
        return stopName.includes(userDest) || 
               userDest.includes(stopName) ||
               // Handle common variations and specific matches
               (stopName.includes('hospital') && userDest.includes('hospital')) ||
               (stopName.includes('visitas') && userDest.includes('visitas')) ||
               (stopName.includes('consultas') && userDest.includes('consultas')) ||
               (stopName.includes('centro') && userDest.includes('centro')) ||
               (stopName.includes('estação') && (userDest.includes('station') || userDest.includes('estacao')));
      });
      
      const hasTime = parsedData.time && parsedData.time !== currentTime;
      
      if (exactOriginMatch && exactDestMatch && hasTime) {
        // User provided exact matches with time - create request
        responseType = 'accepted';
        parsedData.originStopId = exactOriginMatch.stop_id;
        parsedData.destStopId = exactDestMatch.stop_id;
        
        // Save to DynamoDB
        const timeToUse = parsedData.time && parsedData.time !== 'null' ? parsedData.time : currentTime;
        const requestedPickupAt = `${parsedData.date} ${timeToUse}:00`;
        await saveBusRequest(exactOriginMatch.stop_id, exactDestMatch.stop_id, requestedPickupAt);
        
        responseMessage = `✅ Bus request created!\nFrom: ${exactOriginMatch.name}\nTo: ${exactDestMatch.name}\nPickup: ${parsedData.time}`;
      } else {
        // Multiple matches - ask for clarification
        let clarificationText = '';
        
        if (originStops.length > 1) {
          const originNames = [...new Set(originStops.map(s => s.name))];
          clarificationText += `Origin options:\n${originNames.map((name, i) => `${i + 1}. ${name}`).join('\n')}\n\n`;
        }
        
        if (destStops.length > 1) {
          const destNames = [...new Set(destStops.map(s => s.name))];
          clarificationText += `Destination options:\n${destNames.map((name, i) => `${i + 1}. ${name}`).join('\n')}\n\n`;
        }
        
        if (!hasTime) {
          clarificationText += 'Please specify pickup time\n\n';
        }
        
        clarificationText += 'Please be more specific with the exact stop names.';
        
        responseMessage = `Welcome to QuickBus! Our flexible service adapts routes to your needs with no fixed schedules.\n\n${clarificationText}`;
      }
    }

    return {
      statusCode: 200,
      body: JSON.stringify({ 
        transcript: message, 
        lexResponse: { 
          parsedData,
          responseType,
          message: responseMessage
        }
      }),
    };

  } catch (err) {
    console.error("Lambda error:", err);
    console.error("Error stack:", err.stack);
    
    // Return detailed error for debugging
    return {
      statusCode: 200, // Return 200 to avoid React error handling
      body: JSON.stringify({ 
        transcript: message || "unknown",
        lexResponse: { 
          parsedData: {
            origin: "error",
            destination: "error", 
            time: "not specified",
            date: "not specified"
          },
          responseType: 'error',
          message: `Lambda error: ${err.message}. Check CloudWatch logs for details.`,
          stationOptions: null
        }
      }),
    };
  }
};