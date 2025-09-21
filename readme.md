# PROJECT\_NAME

> A smart bus routing system that reduces waiting time and trip duration by providing flexible routes, while remaining accessible to everyone — even those unfamiliar with modern apps.

---

## Table of contents

* Quick start
* Description
* Features
* Tech stack
* Usage
* Roadmap
* Authors
* Troubleshooting / FAQ
* Changelog

---

# Quick start

Clone the repository and install dependencies for each component, then start the system:

```bash
# clone
git clone https://github.com/SwamiCarvalho/Geekhathon2025.git

# install dependencies for routePlanning
cd routePlanning
python3 -m pip install -r requirements.txt

# install dependencies for messagingSimulator
cd ../messagingSimulator
npm install

# run project
cd ..
python3 start_systems.py

# start both systems
Reply with 1
```

---

# Description

This project provides an innovative solution for bus systems, aiming to:

* Reduce waiting times.
* Shorten trip durations.
* Replace rigid, pre-defined routes with **flexible and optimized routes**.
* Stay **accessible to everyone**, including older people who may find traditional transport apps too complex.

In this early development phase, the user connects to the system through a **WebApp that mimics text messages**. By interacting in a simple chat-like interface, the user provides basic information such as:

* From where the user wants to depart.
* Desired destination.
* Preferred departure time.

The application then uses a dataset of known bus stops to suggest possible routes and provides pickup/drop-off options. Behind the scenes, the system dynamically rearranges bus assignments and routes to optimize efficiency, instead of relying on fixed, pre-built routes.

---

# Features

* **Bus ride booking** — request and confirm bus rides directly through the WebApp.
* **Dynamic bus routes** — buses are rerouted in real time to minimize waiting time and trip duration.
* **On-demand riding** — flexible pickups and drop-offs, based on user requests instead of fixed routes.

---

# Tech stack

* **Frontend:** HTML, Tailwind CSS, JavaScript + React
* **Backend:** Node.js, Python + Flask
* **Database:** DynamoDB
* **AWS Services:** Bedrock, LocationService

---

# Usage

After starting the system, interact with the WebApp to request a bus ride. The WebApp is supposed to simulate text messages, so you need to pay attention to the responses!

### Example

1. Go to the WebApp.
2. Send a message, for example, requesting:
   *“From Piscinas Municipais to Avenida Marquês de Pombal at 3 PM”*.
3. Pay attention to the chat, in case more information is needed.
4. If you receive a confirmation, you should see on the **Map App** (which resembles the driver’s view) that the map updates with the new route to pick you up.

---

# Roadmap

* Add real support for SMS bookings
* Add support for bookings through phone call
* Possibility to add dynamic stops (if legal situations are cleared out)

---

# Authors

* [SwamiCarvalho](https://github.com/SwamiCarvalho)
* [samuelaguiar99](https://github.com/samuelaguiar99)
* [danielTeniente](https://github.com/danielTeniente)
* [bruninhari](https://github.com/bruninhari)

---

# Troubleshooting / FAQ

--


