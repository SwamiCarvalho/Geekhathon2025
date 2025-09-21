import React, { useState } from 'react';
import { Send, Phone } from 'lucide-react';

const LEX_LAMBDA_URL = 'https://rsnxivhcmh4ubkrf52htu7u5di0uxwjh.lambda-url.us-east-1.on.aws/'; 
//const LEX_LAMBDA_URL = 'https://ioxuvzzxueotd2zrl6ydscoaem0hpkhs.lambda-url.us-east-1.on.aws/'; 

const BusBookingApp = () => {
  const [messages, setMessages] = useState([
    { type: 'bot', text: 'Hi! I can help you book a bus ride. Just type your request!' }
  ]);
  const [inputText, setInputText] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [sessionId] = useState(`session-${Date.now()}`);

  const addMessage = (type, text) => {
    setMessages(prev => [...prev, { type, text, timestamp: new Date() }]);
  };

  const handleTextSubmit = async () => {
    if (!inputText.trim()) return;

    addMessage('user', inputText);
    setIsProcessing(true);

    try {

      const resp = await fetch(LEX_LAMBDA_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: inputText, sessionId })
      });

      if (!resp.ok) throw new Error(`HTTP error! status: ${resp.status}`);
      const { lexResponse } = await resp.json();


      // Extract message from Bedrock response
      let lexMessage;
      
      if (lexResponse?.parsedData) {
        const { origin, destination, time, date, closest_station } = lexResponse.parsedData;
        lexMessage = `Confirmed receiving request for bus rides from: ${origin}, to ${destination}, at ${time} on ${date}! The closest bus stop is ${closest_station}.`;
      } else {
        lexMessage = 'Could not parse your request. Please use format: "I want to go from [origin] to [destination] at [time] on [date]"';
      }
      
      addMessage('bot', lexMessage);

    } catch (err) {
      console.error('Lex text error:', err.stack);
      addMessage('bot', '❌ Error talking to Lex.');
    } finally {
      setInputText('');
      setIsProcessing(false);
    }
  };

  return (
    <div className="flex justify-center items-center min-h-screen bg-gray-900 p-4">
      <div className="bg-gray-800 rounded-[2.5rem] p-2 shadow-2xl w-80">
        <div className="bg-gray-900 rounded-[2rem] h-[640px] overflow-hidden flex flex-col">

          {/* Header */}
          <div className="bg-gradient-to-r from-indigo-600 to-purple-700 text-white p-4 pb-6 flex justify-between items-center">
            <div className="flex items-center gap-2 justify-center"><Phone className="w-5 h-5" />QuickBus</div>
            
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-gray-800">
            {messages.map((msg, i) => (
              <div key={i} className={`flex ${msg.type === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-xs p-3 rounded-2xl ${msg.type === 'user'
                  ? 'bg-indigo-600 text-white'
                  : 'bg-gray-700 text-gray-100 border border-gray-600'}`}>
                  <p className="text-sm whitespace-pre-line">{msg.text}</p>
                  {msg.timestamp && (
                    <div className="text-xs mt-1 text-gray-400">
                      {msg.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Input */}
          <div className="border-t border-gray-600 bg-gray-900 p-4 space-y-3 flex flex-col">
            <div className="flex gap-2">
              <input
                type="text"
                value={inputText}
                onChange={e => setInputText(e.target.value)}
                onKeyPress={e => e.key === 'Enter' && handleTextSubmit()}
                placeholder="Type your bus request..."
                className="flex-1 p-3 border border-gray-600 rounded-xl bg-gray-800 text-white placeholder-gray-400 focus:outline-none"
              />
              <button
                onClick={handleTextSubmit}
                className="p-3 bg-indigo-600 text-white rounded-xl"
                disabled={isProcessing}>
                <Send className="w-4 h-4" />
              </button>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
};

export default BusBookingApp;
