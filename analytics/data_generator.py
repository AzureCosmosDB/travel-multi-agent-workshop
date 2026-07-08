"""
Data Generation Agent for the Travel Multi-Agent Application.

Simulates realistic users having multi-turn conversations with the travel
assistant, generating memories, trips, and rich conversation data in Cosmos DB
for analytics demos.

Usage:
    # Ensure the travel app is running on http://localhost:8000
    # (and the MCP server on http://localhost:8080)

    python data_generator.py                         # Run all personas
    python data_generator.py --personas 3            # Run first 3 personas only
    python data_generator.py --base-url http://...   # Custom base URL
    python data_generator.py --tenant acme           # Custom tenant
    python data_generator.py --delay 2               # 2s delay between messages
    python data_generator.py --dry-run               # Print plan without calling API
"""

import argparse
import json
import logging
import sys
import time
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("datagen")

# ============================================================================
# Configuration
# ============================================================================

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TENANT = "analytics_demo"
DEFAULT_DELAY = 3  # seconds between messages (give agents time to process)
DEFAULT_TIMEOUT = 300  # seconds per request (agents can be slow on itinerary creation)


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class UserPersona:
    """A simulated user with preferences and planned conversations."""
    user_id: str
    name: str
    age: int
    gender: str
    email: str
    address: dict
    conversations: list  # list of Conversation


@dataclass
class Conversation:
    """A multi-turn conversation that a simulated user will have."""
    title: str
    messages: list[str]  # user messages to send in order


# ============================================================================
# Persona Definitions — 12 diverse users with multiple conversations each
# ============================================================================

PERSONAS: list[UserPersona] = [

    # ---- PERSONA 1: Budget backpacker, dietary restrictions ----
    UserPersona(
        user_id="maya_chen",
        name="Maya Chen",
        age=24,
        gender="female",
        email="maya.chen@example.com",
        address={"street": "45 Sunset Blvd", "city": "San Francisco", "state": "CA", "zipCode": "94110", "country": "United States"},
        conversations=[
            Conversation(
                title="Bangkok budget trip",
                messages=[
                    "Hi! I'm planning a solo backpacking trip to Bangkok.",
                    "I'm a strict vegan and I need budget-friendly options. Find me hostels or cheap guesthouses near Khao San Road.",
                    "I always prefer to stay in places with a social atmosphere where I can meet other travelers.",
                    "Show me vegan restaurants in Bangkok. I love street food and I always eat at local markets rather than tourist spots.",
                    "What activities do you recommend? I'm really into cooking classes and temple visits.",
                    "I like to start my mornings early and do the main sightseeing before it gets too hot.",
                    "I also want to visit a floating market. Which one is the most authentic?",
                    "Can you suggest a good night market for shopping? I always spend my evenings exploring markets.",
                    "I think I want to try a traditional Thai massage too. Where is best?",
                    "OK I have everything I need. Create a 4-day itinerary for April 5-8, 2026 please.",
                ],
            ),
            Conversation(
                title="Tokyo on a budget",
                messages=[
                    "I want to visit Tokyo next! Still on a tight budget though.",
                    "Find me affordable capsule hotels or hostels in Shinjuku area.",
                    "I need vegan ramen places -- do they exist in Tokyo? Show me restaurants with vegan options.",
                    "I always walk everywhere instead of taking taxis. What free activities can I do on foot?",
                    "I want to visit Akihabara for electronics and anime culture. What are the best shops?",
                    "What about Harajuku? I hear the street fashion is amazing. Show me activities there.",
                    "Show me the best spots for cherry blossom viewing. I prefer quieter parks over crowded tourist spots.",
                    "I also want to visit a traditional Japanese garden. Shinjuku Gyoen?",
                    "Find me budget-friendly izakayas that have vegan options. I usually eat dinner around 7pm.",
                    "Perfect, create a 3-day Tokyo plan for May 1-3, 2026.",
                ],
            ),
            Conversation(
                title="Updating preferences",
                messages=[
                    "Hey, quick update -- I've started eating eggs now, so I'm vegan except for eggs.",
                    "Also, I realize I really prefer staying in places with good wifi since I work remotely sometimes.",
                    "Can you remember that I'm allergic to peanuts too? That's important for restaurants.",
                    "Actually you know what, I've started eating seafood too. So I'm pescatarian now, not vegan.",
                ],
            ),
        ],
    ),

    # ---- PERSONA 2: Luxury couple / honeymoon ----
    UserPersona(
        user_id="james_mitchell",
        name="James Mitchell",
        age=34,
        gender="male",
        email="james.mitchell@example.com",
        address={"street": "12 Park Avenue", "city": "New York", "state": "NY", "zipCode": "10016", "country": "United States"},
        conversations=[
            Conversation(
                title="Paris honeymoon",
                messages=[
                    "My wife and I are planning our honeymoon in Paris! We want the most romantic experience possible.",
                    "Find us a luxury 5-star hotel with a view of the Eiffel Tower. Spa is a must.",
                    "We always prefer boutique hotels with character over big chain hotels.",
                    "Show us the best fine dining restaurants in Paris. We both love French cuisine and money is no object.",
                    "We always eat dinner late, around 9pm, so we need restaurants that serve late.",
                    "What activities do you recommend? We enjoy wine tasting, art galleries, and sunset river cruises.",
                    "We also want a private cooking class where we can learn to make French pastries together.",
                    "Which Michelin-starred restaurants should we definitely not miss? We love tasting menus.",
                    "We prefer to take our time at each place rather than rushing through a packed schedule.",
                    "Create a 5-day honeymoon itinerary for June 10-14, 2026. Make it unforgettable!",
                ],
            ),
            Conversation(
                title="Anniversary in Rome",
                messages=[
                    "We loved Paris so much! Now planning our first anniversary trip to Rome.",
                    "Find us a 5-star hotel near the Colosseum or Spanish Steps. Same luxury style as Paris.",
                    "Show us the best Italian restaurants. We discovered we love truffle dishes in Paris.",
                    "We want a private tour of the Vatican and a sunset visit to the Colosseum. What activities are available?",
                    "We always book private tours instead of group tours. More intimate that way.",
                    "Find us a rooftop bar or restaurant with a view of the Roman Forum.",
                    "Are there any exclusive culinary experiences? Like a private pasta-making class?",
                    "Show us restaurants in Trastevere. We heard it is the most charming neighborhood.",
                    "We never skip dessert. Can we do a gelato tasting tour?",
                    "Build us a 4-day itinerary for October 15-18, 2026.",
                ],
            ),
            Conversation(
                title="Updating preferences",
                messages=[
                    "We prefer boutique hotels now, not big luxury chains. My wife has gone vegetarian.",
                    "Also, please note we love outdoor terrace dining when the weather is nice.",
                    "She is especially into farm-to-table restaurants with seasonal menus.",
                ],
            ),
        ],
    ),

    # ---- PERSONA 3: Family with kids ----
    UserPersona(
        user_id="sarah_johnson",
        name="Sarah Johnson",
        age=38,
        gender="female",
        email="sarah.j@example.com",
        address={"street": "789 Oak Lane", "city": "Chicago", "state": "IL", "zipCode": "60614", "country": "United States"},
        conversations=[
            Conversation(
                title="London family vacation",
                messages=[
                    "I'm planning a family trip to London with my two kids, ages 6 and 10.",
                    "We need a family-friendly hotel with connecting rooms. Somewhere near the Tube would be great.",
                    "The kids are picky eaters -- they need places with good kids menus. My daughter is gluten-free.",
                    "What kid-friendly activities are there? They love the Harry Potter studios and interactive museums.",
                    "I also need some wheelchair-accessible options because my mother might join us, and she uses a wheelchair.",
                    "What about the Natural History Museum? My son is obsessed with dinosaurs.",
                    "Are there any good parks or playgrounds near central London for the kids to burn off energy?",
                    "Can you suggest a family-friendly afternoon tea place? The kids think it sounds fancy.",
                    "What is the best way to get around London with kids -- Tube or buses?",
                    "Create a 5-day London plan for July 20-24, 2026.",
                ],
            ),
            Conversation(
                title="Barcelona family beach trip",
                messages=[
                    "We want a beach vacation next -- thinking Barcelona!",
                    "Find family-friendly beachfront hotels with a pool. The kids love swimming.",
                    "We need restaurants that are good for families with gluten-free options.",
                    "What about activities for the kids? They'd love an aquarium or a fun park.",
                    "I want at least one day to visit Sagrada Familia and Park Guell while the kids are at the pool.",
                    "Is there a kids club or babysitting service at any of those hotels? We'd love one evening out alone.",
                    "What about ice cream shops? The kids will revolt without daily gelato.",
                    "Are there any family-friendly flamenco shows? My daughter would love that.",
                    "How walkable is Barcelona for a family with a stroller? My youngest gets tired quickly.",
                    "Make us a 4-day itinerary for August 5-8, 2026.",
                ],
            ),
        ],
    ),

    # ---- PERSONA 4: Business traveler ----
    UserPersona(
        user_id="david_okafor",
        name="David Okafor",
        age=42,
        gender="male",
        email="david.okafor@example.com",
        address={"street": "55 High Street", "city": "London", "state": "", "zipCode": "EC2R 8AH", "country": "United Kingdom"},
        conversations=[
            Conversation(
                title="Singapore business trip",
                messages=[
                    "I have a business conference in Singapore next month. Need to plan around my meetings.",
                    "Find me a business hotel with a good executive lounge and fast wifi. Near Marina Bay if possible.",
                    "I always stay at hotels with an executive lounge because I work late and need 24-hour coffee.",
                    "I eat halal food. Show me good halal restaurants near the conference center.",
                    "I'll have free evenings -- find me the best cocktail bars and nightlife spots.",
                    "I always like to explore local food when traveling. Which hawker centers have the best halal stalls?",
                    "What activities can I do on my last day? Gardens by the Bay looks amazing.",
                    "Is there a good rooftop bar at Marina Bay Sands? I hear the view is incredible.",
                    "I prefer to pack my schedule tight -- I never waste time on a business trip.",
                    "Plan a 3-day trip for March 20-22, 2026. Conference is 9am-5pm each day.",
                ],
            ),
            Conversation(
                title="Dubai client meeting",
                messages=[
                    "I need to visit our Dubai office next quarter.",
                    "Find me a 5-star business hotel in Downtown Dubai or DIFC area.",
                    "I'll need halal fine dining options for entertaining clients.",
                    "I also want to squeeze in a desert safari on the weekend after my meetings.",
                    "Which restaurants are best for impressing international clients? Something with a view of the Burj Khalifa.",
                    "Can you find a hotel with a good gym and pool? I like to work out in the mornings.",
                    "What is the dress code like for upscale restaurants in Dubai?",
                    "I hear the Dubai Mall has an aquarium inside. Is it worth a quick visit between meetings?",
                    "Any good cigar lounges or whisky bars for a relaxed evening?",
                    "Create a 4-day plan for November 3-6, 2026.",
                ],
            ),
            Conversation(
                title="Frankfurt conference",
                messages=[
                    "Quick trip to Frankfurt for a fintech conference.",
                    "I need a hotel near Messe Frankfurt with good transport links.",
                    "Find me restaurants with halal options near the conference venue.",
                    "What about local specialties I should try? Are there any traditional German dishes that are halal-friendly?",
                    "I'll have one free evening. What is there to do in Frankfurt at night?",
                    "Is the Sachsenhausen district walkable from the conference? I hear there are good apple wine taverns.",
                    "Can you suggest a nice coffee shop where I can take a morning call before the conference?",
                    "What about the Romerberg area? Worth a quick visit for the architecture?",
                    "I might have time for breakfast meetings. What hotel restaurants are best for that?",
                    "Build a 2-day itinerary for September 15-16, 2026. Very meeting-heavy, just need dinner spots and any quick sightseeing.",
                ],
            ),
        ],
    ),

    # ---- PERSONA 5: Adventure solo traveler ----
    UserPersona(
        user_id="elena_vasquez",
        name="Elena Vasquez",
        age=29,
        gender="female",
        email="elena.v@example.com",
        address={"street": "Calle Gran Via 42", "city": "Madrid", "state": "", "zipCode": "28013", "country": "Spain"},
        conversations=[
            Conversation(
                title="New Zealand adventure",
                messages=[
                    "I want an adventure trip to New Zealand! Hiking, bungee jumping, the works.",
                    "I prefer eco-lodges or adventure lodges over regular hotels. Something close to nature.",
                    "I'm vegetarian but not super strict -- I eat fish occasionally. I love farm-to-table restaurants.",
                    "What are the best hiking trails and adventure activities in Auckland and Christchurch?",
                    "I'm also interested in Maori cultural experiences.",
                    "Can you tell me more about the Milford Track? Is it doable in one day or do I need a multi-day hike?",
                    "I want to try white water rafting too. Where is the best spot for that?",
                    "What about wildlife? I'd love to see kiwi birds in the wild.",
                    "Are there any good farmers markets or local food festivals happening in March?",
                    "Create a 6-day adventure itinerary for March 1-6, 2026 splitting time between Auckland and Christchurch.",
                ],
            ),
            Conversation(
                title="Iceland/Reykjavik adventure",
                messages=[
                    "Next on my list -- Iceland! I want to see the Northern Lights and do glacier hiking.",
                    "Find me cozy lodges or boutique hotels near the Golden Circle route.",
                    "I want restaurants that serve traditional Icelandic food. I'm fine with fish and seafood.",
                    "What's the best way to see the Northern Lights? Any guided tours?",
                    "I've heard about ice cave tours inside glaciers. Can you find one?",
                    "What about the Blue Lagoon? Is it overhyped or worth visiting?",
                    "I want to try snorkeling in Silfra fissure between the tectonic plates. Is that possible in December?",
                    "Are there any good hot springs that are less touristy than the Blue Lagoon?",
                    "Can you recommend a restaurant that serves the traditional Icelandic lamb soup?",
                    "Plan a 4-day trip to Reykjavik for December 10-13, 2026.",
                ],
            ),
        ],
    ),

    # ---- PERSONA 6: Retired couple ----
    UserPersona(
        user_id="robert_williams",
        name="Robert Williams",
        age=68,
        gender="male",
        email="bob.williams@example.com",
        address={"street": "234 Maple Drive", "city": "Seattle", "state": "WA", "zipCode": "98101", "country": "United States"},
        conversations=[
            Conversation(
                title="Mediterranean cruise prep - Barcelona stop",
                messages=[
                    "My wife and I are doing a Mediterranean cruise and we have a full day in Barcelona.",
                    "We move slowly -- no rushed tours. We need places that are senior-friendly and not too strenuous.",
                    "We're on a low-sodium diet due to heart health. Can you find restaurants that accommodate that?",
                    "We love classical architecture and history. The Sagrada Familia is on our list.",
                    "We also want a nice relaxed lunch spot with a view.",
                    "Is there a way to get skip-the-line tickets for Sagrada Familia? We can't stand in the heat too long.",
                    "What about the Gothic Quarter? Is it walkable for someone who needs frequent rest breaks?",
                    "Can you recommend a quiet cafe near Las Ramblas where we can sit and people-watch?",
                    "Are there any classical music performances or concerts happening that day?",
                    "Create a 1-day Barcelona itinerary for September 8, 2026.",
                ],
            ),
            Conversation(
                title="Lisbon slow travel",
                messages=[
                    "We want to spend a week in Lisbon. Slow travel -- no rushing!",
                    "Find us a comfortable hotel with elevator access. Walking is hard with all the hills.",
                    "We always choose hotels that are close to public transport so we do not have to walk far.",
                    "I have a nut allergy and my wife is lactose intolerant. Show us restaurants that can accommodate both.",
                    "We enjoy fado music, historic trams, and pastry shops. What activities do you recommend?",
                    "We always take an afternoon nap, so we prefer light mornings and evening activities.",
                    "Find us a traditional fado restaurant where we can have dinner and a show.",
                    "We prefer to eat dinner early, around 6pm, not the typical late European schedule.",
                    "My wife loves tiles and mosaics. Is there a good tile museum or workshop to visit?",
                    "Make us a 5-day Lisbon plan for April 20-24, 2026.",
                ],
            ),
            Conversation(
                title="Vienna cultural trip",
                messages=[
                    "We're thinking about Vienna next year. We love classical music and opera.",
                    "Find us a grand hotel -- something historic, near the opera house.",
                    "What are the best places for afternoon Viennese coffee and pastries?",
                    "We want tickets to a Mozart concert or opera performance.",
                    "Is the Spanish Riding School worth visiting? We've seen it in documentaries.",
                    "Can you find a restaurant that does traditional Wiener Schnitzel? Low sodium options would be a bonus.",
                    "What about the Belvedere Palace? Is it accessible for folks who can't do lots of stairs?",
                    "Are there hop-on hop-off buses? That might be easier than walking everything.",
                    "My wife wants to visit Naschmarkt food market. Is it easy to navigate?",
                    "Plan a 4-day cultural trip for May 5-8, 2026.",
                ],
            ),
        ],
    ),

    # ---- PERSONA 7: College spring break group ----
    UserPersona(
        user_id="jordan_taylor",
        name="Jordan Taylor",
        age=21,
        gender="non-binary",
        email="jtaylor@university.edu",
        address={"street": "100 University Blvd", "city": "Austin", "state": "TX", "zipCode": "78712", "country": "United States"},
        conversations=[
            Conversation(
                title="Miami spring break",
                messages=[
                    "Spring break! Me and 5 friends want to go to Miami.",
                    "We need the cheapest possible hotel near South Beach. We don't care about luxury -- just clean and close to the action.",
                    "We're all about nightlife -- clubs, pool parties, beach bars. What's the best scene?",
                    "For food, we need cheap eats. Tacos, burgers, pizza. Nothing fancy.",
                    "Any must-do activities during the day? We like jet skiing and paddleboarding.",
                    "What about a boat party or catamaran cruise? That sounds fun for the group.",
                    "Are there any free or cheap live music events on the beach?",
                    "We heard Wynwood Walls has great street art and bars. Is it worth the trip from South Beach?",
                    "Can you recommend a good brunch spot? We'll probably need a late breakfast most days.",
                    "Create a 4-day spring break plan for March 14-17, 2026!",
                ],
            ),
            Conversation(
                title="Amsterdam plan B",
                messages=[
                    "Actually some friends can't do Miami. What about a budget trip? Maybe Amsterdam instead?",
                    "Find us the cheapest hostels or party hostels in Amsterdam.",
                    "We want the best coffee shops, markets, and canal tours.",
                    "What about the nightlife scene there?",
                    "Are there any good street food markets? We're on a tight budget for food.",
                    "Can we rent bikes? I heard that's the best way to get around the city.",
                    "What about the Anne Frank House? We should probably do something cultural.",
                    "Are there any free walking tours of the city?",
                    "What neighborhoods have the best vibe for a group of college students?",
                    "Plan a 3-day trip for March 14-16, 2026.",
                ],
            ),
        ],
    ),

    # ---- PERSONA 8: Food tourism enthusiast ----
    UserPersona(
        user_id="priya_sharma",
        name="Priya Sharma",
        age=31,
        gender="female",
        email="priya.sharma@example.com",
        address={"street": "14 Juhu Tara Road", "city": "Mumbai", "state": "Maharashtra", "zipCode": "400049", "country": "India"},
        conversations=[
            Conversation(
                title="Tokyo food tour",
                messages=[
                    "I'm a food blogger and I'm planning a food-focused trip to Tokyo!",
                    "I want hotels near Tsukiji/Toyosu market area. Boutique or design hotels preferred.",
                    "I need to visit the best sushi restaurants, ramen shops, and izakayas. I eat everything!",
                    "I'm interested in food tours, cooking classes, and visits to sake breweries.",
                    "Also want to experience a traditional kaiseki dinner. Where's the best one?",
                    "What about depachika -- the department store basement food halls? Which ones are the best?",
                    "I've heard about omakase counters where the chef decides the menu. Can you find a great one?",
                    "Are there any street food alleys or yokocho I should visit for late night eats?",
                    "What is the best time to visit Toyosu fish market for the tuna auction?",
                    "Plan a 5-day Tokyo food pilgrimage for April 15-19, 2026.",
                ],
            ),
            Conversation(
                title="Istanbul food adventure",
                messages=[
                    "Next food destination: Istanbul! I've heard the street food is incredible.",
                    "I want a hotel in the Sultanahmet or Beyoglu area with good restaurant access.",
                    "Find me the best kebab restaurants, baklava shops, and meze places.",
                    "I want a Turkish cooking class where I can learn to make pide and lahmacun.",
                    "Also interested in a Bosphorus dinner cruise.",
                    "What about Turkish breakfast -- I hear it is a massive spread. Where is the best one?",
                    "Can you find a place where I can try authentic Turkish delight and learn how it's made?",
                    "I want to visit the Spice Bazaar. What should I buy there for cooking back home?",
                    "Are there any hidden local restaurants that tourists don't know about?",
                    "Create a 4-day food itinerary for May 10-13, 2026.",
                ],
            ),
            Conversation(
                title="Copenhagen Nordic cuisine",
                messages=[
                    "I want to explore New Nordic cuisine in Copenhagen!",
                    "Find me restaurants focused on foraging, local ingredients, and innovative techniques.",
                    "I'd love to visit a food market -- Torvehallerne or something similar.",
                    "What about smorrebrod? Where's the best traditional Danish open sandwich?",
                    "Are there any restaurants that do chef's table experiences? I want to see the kitchen in action.",
                    "I've heard about a restaurant that serves food made entirely from food waste -- can you find it?",
                    "What about Danish pastries? Where can I find the best kanelsnegle and wienerbroed?",
                    "Is there a food tour that covers multiple neighborhoods and local specialties?",
                    "Can you recommend a cozy hygge-style cafe for an afternoon coffee and cake?",
                    "Plan a 3-day Copenhagen food trip for June 5-7, 2026.",
                ],
            ),
            Conversation(
                title="Updating dietary needs",
                messages=[
                    "I've developed a shellfish allergy recently. Please remember that for all future restaurant recommendations.",
                    "I can still eat fish and other seafood, just no shrimp, crab, lobster, or shellfish.",
                ],
            ),
        ],
    ),

    # ---- PERSONA 9: Digital nomad ----
    UserPersona(
        user_id="alex_brennan",
        name="Alex Brennan",
        age=27,
        gender="male",
        email="alex@remotework.io",
        address={"street": "Nomad", "city": "Portland", "state": "OR", "zipCode": "97209", "country": "United States"},
        conversations=[
            Conversation(
                title="Lisbon remote work base",
                messages=[
                    "I'm a digital nomad looking for a month-long base in Lisbon.",
                    "I need a hotel or apartment-hotel with amazing wifi and a workspace. Co-working friendly area preferred.",
                    "I'm pescatarian and love craft coffee. Find me the best specialty coffee shops and seafood restaurants.",
                    "During my downtime, I want to surf, explore street art, and hang out in Bairro Alto.",
                    "What about co-working spaces? I need one with fast internet and a good community vibe.",
                    "Are there any good surf schools near Lisbon? I've always wanted to learn.",
                    "Can you recommend a quiet restaurant with outdoor seating where I can take a work call during lunch?",
                    "I heard Timeout Market has great food stalls. Is it worth visiting or too touristy?",
                    "What neighborhoods are best for nightlife and meeting other remote workers?",
                    "Plan a 5-day highlights itinerary for my first week, September 1-5, 2026.",
                ],
            ),
            Conversation(
                title="Bali workation",
                messages=[
                    "Thinking about Bali next. I hear Canggu is great for remote workers.",
                    "I need places with reliable internet and good coffee shops to work from.",
                    "I want to try surfing lessons and visit rice terraces on weekends.",
                    "For food, I'm still pescatarian. Love fresh seafood and smoothie bowls.",
                    "What co-working spaces in Canggu have the best internet and community?",
                    "Are there any yoga classes or wellness retreats I can drop into after work hours?",
                    "I heard Ubud is more cultural and less surfy than Canggu. Worth a weekend trip?",
                    "What about hidden waterfalls? I keep seeing photos online and they look amazing.",
                    "Can you find me a villa or guesthouse with a pool and fast wifi in Canggu?",
                    "Create a 7-day Bali itinerary for October 10-16, 2026 mixing work and exploration.",
                ],
            ),
            Conversation(
                title="Updating work preferences",
                messages=[
                    "Hey, I want to update my preferences. Fast reliable wifi is my absolute top priority when choosing accommodation.",
                    "I also prefer places with a desk or workspace in the room.",
                    "And I've gone fully vegetarian now -- no more fish.",
                ],
            ),
        ],
    ),

    # ---- PERSONA 10: Art & culture enthusiast ----
    UserPersona(
        user_id="isabelle_dupont",
        name="Isabelle Dupont",
        age=45,
        gender="female",
        email="isabelle.dupont@galerie.fr",
        address={"street": "18 Rue de Rivoli", "city": "Paris", "state": "", "zipCode": "75001", "country": "France"},
        conversations=[
            Conversation(
                title="Amsterdam art tour",
                messages=[
                    "I'm an art gallery curator planning a research trip to Amsterdam.",
                    "I want a design hotel or boutique hotel in the Jordaan or Museum Quarter.",
                    "I need to visit the Rijksmuseum, Van Gogh Museum, and Stedelijk Museum. Any hidden gem galleries?",
                    "For dining, I love farm-to-table and organic restaurants. I'm a flexitarian.",
                    "Are there any contemporary art fairs or gallery openings happening?",
                    "What about the FOAM photography museum? I've heard great things.",
                    "Can you find galleries that specialize in Dutch Golden Age paintings? That's my area of research.",
                    "I'd love a nice wine bar near the museum district for unwinding after gallery visits.",
                    "Are there any artist studio tours or open ateliers I can visit?",
                    "Create a 3-day art-focused Amsterdam itinerary for April 2-4, 2026.",
                ],
            ),
            Conversation(
                title="Berlin contemporary art scene",
                messages=[
                    "Berlin is next on my research list. I hear the contemporary art scene is incredible.",
                    "Find me a hotel in Kreuzberg or Mitte -- somewhere with character.",
                    "I need to visit gallery districts, artist studios, and the East Side Gallery.",
                    "What about restaurants in the art district? I love experimental cuisine.",
                    "Are there any art bookshops or print shops I should visit?",
                    "I've heard about the Hamburger Bahnhof museum -- is it a must-see for contemporary art?",
                    "What about the KW Institute for Contemporary Art? Do they have anything on right now?",
                    "Can you recommend a trendy cafe in Kreuzberg where the local creative crowd hangs out?",
                    "I'm interested in street art tours of Berlin. Is there a good guided one?",
                    "Build a 4-day Berlin art itinerary for October 1-4, 2026.",
                ],
            ),
        ],
    ),

    # ---- PERSONA 11: Wellness / yoga retreat seeker ----
    UserPersona(
        user_id="aisha_rahman",
        name="Aisha Rahman",
        age=35,
        gender="female",
        email="aisha.r@wellness.com",
        address={"street": "7 Garden District", "city": "Dubai", "state": "", "zipCode": "00000", "country": "United Arab Emirates"},
        conversations=[
            Conversation(
                title="Bali wellness retreat",
                messages=[
                    "I'm planning a wellness retreat in Bali. I want to find places focused on meditation and yoga.",
                    "I eat strictly halal food and I'm looking for healthy, organic restaurant options.",
                    "I want spa treatments -- traditional Balinese massage, herbal treatments.",
                    "What about sunrise yoga sessions overlooking rice paddies?",
                    "I also want to visit water temples and learn about Balinese spirituality.",
                    "Can you find me a retreat center in Ubud that offers daily yoga and meditation classes?",
                    "I'm interested in sound healing sessions. Are there any practitioners in Bali?",
                    "What about healthy cooking classes using local Balinese ingredients?",
                    "Is there a good halal restaurant in Ubud? I know it might be harder to find there.",
                    "Create a 5-day Bali wellness retreat itinerary for April 1-5, 2026.",
                ],
            ),
            Conversation(
                title="Stockholm wellness getaway",
                messages=[
                    "I want a Scandinavian wellness experience in Stockholm.",
                    "Find me hotels with great spa facilities -- especially saunas and cold plunge pools.",
                    "I eat halal and prefer clean, healthy food. Scandinavian food culture seems perfect.",
                    "What outdoor activities combine wellness and nature? Forest bathing, archipelago kayaking?",
                    "Are there any traditional Swedish bathhouses or public saunas I should visit?",
                    "I've heard about Finnish-style saunas followed by ice swimming. Is that available in Stockholm?",
                    "Can you recommend a calm, quiet restaurant focused on organic Nordic food?",
                    "What about a day trip to the archipelago? I want to find peace and quiet in nature.",
                    "Are there any guided meditation or mindfulness retreats near Stockholm?",
                    "Create a 3-day Stockholm wellness plan for August 15-17, 2026.",
                ],
            ),
        ],
    ),

    # ---- PERSONA 12: History & architecture enthusiast ----
    UserPersona(
        user_id="marco_rossi",
        name="Marco Rossi",
        age=55,
        gender="male",
        email="marco.rossi@architettura.it",
        address={"street": "Via della Conciliazione 4", "city": "Rome", "state": "", "zipCode": "00193", "country": "Italy"},
        conversations=[
            Conversation(
                title="Prague architectural tour",
                messages=[
                    "I'm an architect and I'm fascinated by Prague's mix of Gothic, Baroque, and Art Nouveau.",
                    "I want a hotel in a historic building -- converted palace or medieval-era hotel would be amazing.",
                    "For restaurants, I enjoy traditional Czech cuisine. I eat everything but I prefer food with local character.",
                    "I need to see the astronomical clock, Prague Castle, and the Cubist architecture district.",
                    "I'm also interested in any architectural walking tours.",
                    "What about the Dancing House by Frank Gehry? Is it worth visiting inside or just seeing from outside?",
                    "Can you find a traditional Czech beer hall with good local food? I want to try svickova and trdelnik.",
                    "Are there any lesser-known Art Nouveau buildings I should seek out?",
                    "I'd love to visit the Jewish Quarter for its historic synagogues. What's the architectural style there?",
                    "Plan a 3-day Prague architecture tour for September 20-22, 2026.",
                ],
            ),
            Conversation(
                title="Istanbul architecture and history",
                messages=[
                    "Istanbul has been on my bucket list -- the Hagia Sophia, Blue Mosque, Byzantine architecture.",
                    "Find me a hotel with character -- maybe a restored Ottoman mansion?",
                    "I want restaurants in historic settings. Roof terrace dining with mosque views.",
                    "I need to visit the basilica cistern, Topkapi Palace, and the Grand Bazaar.",
                    "Are there any architectural boat tours along the Bosphorus?",
                    "Tell me more about the Chora Church mosaics. Are they accessible to visitors?",
                    "I've heard about the Suleymaniye Mosque -- how does it compare architecturally to the Blue Mosque?",
                    "What about the old Ottoman neighborhoods on the Asian side? Worth a half-day trip?",
                    "Can you find a restaurant inside a historic han or caravanserai?",
                    "Build a 5-day Istanbul history and architecture itinerary for November 10-14, 2026.",
                ],
            ),
            Conversation(
                title="Budapest thermal baths and architecture",
                messages=[
                    "Budapest next -- I hear the thermal baths are architectural masterpieces.",
                    "Find me a grand hotel, something from the Habsburg era if possible.",
                    "I want to visit Szechenyi Baths, Gellert Baths, and the Parliament Building.",
                    "Traditional Hungarian restaurants -- goulash, chimney cake, wine bars.",
                    "What about the ruin bars in the Jewish Quarter? I hear they are in amazing old buildings.",
                    "Can you tell me more about the Hungarian Parliament? Can you go inside for a tour?",
                    "I want to walk across the Chain Bridge and visit Buda Castle. What is the architecture like?",
                    "Are there any Art Nouveau thermal baths I might have missed?",
                    "What is the best spot for a panoramic view of the Danube and the city skyline?",
                    "Plan a 3-day trip for July 8-10, 2026.",
                ],
            ),
        ],
    ),
]


# ============================================================================
# API Client
# ============================================================================

class TravelAppClient:
    """HTTP client that talks to the running Travel Multi-Agent API."""

    def __init__(self, base_url: str, timeout: float = 180):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=timeout)

    def health_check(self) -> bool:
        try:
            r = self.client.get(f"{self.base_url}/health")
            return r.status_code == 200
        except httpx.ConnectError:
            return False

    def create_user(self, tenant_id: str, persona: UserPersona) -> dict:
        url = f"{self.base_url}/tenant/{tenant_id}/users"
        body = {
            "userId": persona.user_id,
            "tenantId": tenant_id,
            "name": persona.name,
            "gender": persona.gender,
            "age": persona.age,
            "email": persona.email,
            "address": persona.address,
        }
        r = self.client.post(url, json=body)
        if r.status_code == 409:
            log.info("  User %s already exists — continuing.", persona.user_id)
            return body
        r.raise_for_status()
        return r.json()

    def create_session(self, tenant_id: str, user_id: str) -> str:
        url = f"{self.base_url}/tenant/{tenant_id}/user/{user_id}/sessions"
        r = self.client.post(url, params={"activeAgent": "orchestrator"})
        r.raise_for_status()
        data = r.json()
        return data.get("sessionId") or data.get("id")

    def send_message(self, tenant_id: str, user_id: str, session_id: str, message: str) -> list[dict]:
        url = (
            f"{self.base_url}/tenant/{tenant_id}/user/{user_id}"
            f"/sessions/{session_id}/completion"
        )
        # The API expects a raw JSON string, not an object
        r = self.client.post(
            url,
            content=json.dumps(message),
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()
        return r.json()

    def get_memories(self, tenant_id: str, user_id: str) -> list[dict]:
        url = f"{self.base_url}/tenant/{tenant_id}/user/{user_id}/memories"
        r = self.client.get(url)
        r.raise_for_status()
        return r.json()

    def get_trips(self, tenant_id: str, user_id: str) -> list[dict]:
        url = f"{self.base_url}/tenant/{tenant_id}/user/{user_id}/trips"
        r = self.client.get(url)
        r.raise_for_status()
        return r.json()

    def update_trip(self, tenant_id: str, user_id: str, trip_id: str, updates: dict) -> dict:
        url = f"{self.base_url}/tenant/{tenant_id}/user/{user_id}/trips/{trip_id}"
        r = self.client.put(url, json=updates)
        r.raise_for_status()
        return r.json()

    def close(self):
        self.client.close()


# ============================================================================
# Data Generation Runner
# ============================================================================

class DataGenerationRunner:
    """Orchestrates the full data-generation process."""

    def __init__(
        self,
        client: TravelAppClient,
        tenant_id: str,
        delay: float,
        dry_run: bool = False,
        parallel: int = 1,
    ):
        self.client = client
        self.tenant_id = tenant_id
        self.delay = delay
        self.dry_run = dry_run
        self.parallel = max(1, parallel)
        self._stats_lock = threading.Lock()
        self.stats = {
            "users_created": 0,
            "sessions_created": 0,
            "messages_sent": 0,
            "errors": 0,
        }

    def _inc_stat(self, key: str, n: int = 1):
        with self._stats_lock:
            self.stats[key] += n

    def run(self, personas: list[UserPersona]):
        total_conversations = sum(len(p.conversations) for p in personas)
        total_messages = sum(
            len(m) for p in personas for c in p.conversations for m in [c.messages]
        )
        log.info(
            "=== Data Generation Plan ===\n"
            "  Personas:       %d\n"
            "  Conversations:  %d\n"
            "  Total messages:  %d\n"
            "  Tenant:         %s\n"
            "  Delay:          %.1fs between messages\n"
            "  Parallel:       %d\n"
            "  Dry run:        %s",
            len(personas), total_conversations, total_messages,
            self.tenant_id, self.delay, self.parallel, self.dry_run,
        )

        if self.dry_run:
            self._print_plan(personas)
            return

        # Check app is reachable
        if not self.client.health_check():
            log.error(
                "Cannot reach the Travel API at %s. "
                "Make sure the app is running (python -m uvicorn ...).",
                self.client.base_url,
            )
            sys.exit(1)
        log.info("Travel API is healthy.")

        if self.parallel > 1:
            self._run_parallel(personas)
        else:
            for i, persona in enumerate(personas, 1):
                log.info(
                    "\n{'='*60}\n[%d/%d] PERSONA: %s (%s)\n{'='*60}",
                    i, len(personas), persona.name, persona.user_id,
                )
                self._run_persona(persona, self.client)

        self._print_summary(personas)

    def _run_parallel(self, personas: list[UserPersona]):
        """Run multiple personas concurrently using threads."""
        log.info("Running %d personas in parallel (max %d concurrent)...", len(personas), self.parallel)

        def _worker(idx: int, persona: UserPersona):
            # Each thread gets its own HTTP client (httpx.Client is not thread-safe)
            client = TravelAppClient(base_url=self.client.base_url, timeout=self.client.client.timeout.read)
            try:
                log.info(
                    "\n[%d/%d] PERSONA: %s (%s)",
                    idx, len(personas), persona.name, persona.user_id,
                )
                self._run_persona(persona, client)
            finally:
                client.close()

        with ThreadPoolExecutor(max_workers=self.parallel) as pool:
            futures = {
                pool.submit(_worker, i, p): p
                for i, p in enumerate(personas, 1)
            }
            for future in as_completed(futures):
                persona = futures[future]
                try:
                    future.result()
                except Exception as e:
                    log.error("Persona %s failed: %s", persona.name, e)

    def _run_persona(self, persona: UserPersona, client: TravelAppClient):
        # 1 — Create user
        try:
            client.create_user(self.tenant_id, persona)
            self._inc_stat("users_created")
            log.info("  Created user: %s", persona.name)
        except httpx.HTTPStatusError as e:
            log.warning("  User creation issue for %s: %s", persona.user_id, e)

        # 2 — Run each conversation
        for conv_idx, conv in enumerate(persona.conversations, 1):
            log.info(
                "\n  --- Conversation %d/%d: %s ---",
                conv_idx, len(persona.conversations), conv.title,
            )
            try:
                session_id = client.create_session(self.tenant_id, persona.user_id)
                self._inc_stat("sessions_created")
                log.info("  Session: %s", session_id)
            except httpx.HTTPStatusError as e:
                log.error("  Failed to create session: %s", e)
                self._inc_stat("errors")
                continue

            for msg_idx, message in enumerate(conv.messages, 1):
                log.info(
                    "    [%d/%d] User: %.80s%s",
                    msg_idx, len(conv.messages), message,
                    "..." if len(message) > 80 else "",
                )
                try:
                    response_msgs = client.send_message(
                        self.tenant_id, persona.user_id, session_id, message
                    )
                    self._inc_stat("messages_sent")

                    # Extract the latest assistant response
                    assistant_msgs = [
                        m for m in response_msgs
                        if m.get("senderRole") == "Assistant"
                        or m.get("sender", "").lower() != "user"
                    ]
                    if assistant_msgs:
                        last = assistant_msgs[-1]
                        preview = (last.get("text") or "")[:120]
                        log.info(
                            "    [%s] %.120s%s",
                            last.get("sender", "Agent"),
                            preview,
                            "..." if len(last.get("text", "")) > 120 else "",
                        )
                except httpx.HTTPStatusError as e:
                    log.error("    Message failed (HTTP %s): %s", e.response.status_code, e)
                    self._inc_stat("errors")
                except httpx.ReadTimeout:
                    log.warning("    Message timed out — agents may need more time. Continuing...")
                    self._inc_stat("errors")
                except Exception as e:
                    log.error("    Unexpected error: %s", e)
                    self._inc_stat("errors")

                # Delay between messages
                if msg_idx < len(conv.messages):
                    time.sleep(self.delay)

            # Pause between conversations
            time.sleep(self.delay)

        # 3 — Report on generated data
        try:
            memories = client.get_memories(self.tenant_id, persona.user_id)
            trips = client.get_trips(self.tenant_id, persona.user_id)
            log.info(
                "  >> %s now has %d memories and %d trips.",
                persona.name, len(memories), len(trips),
            )
        except Exception:
            pass

    def _print_plan(self, personas: list[UserPersona]):
        """Dry run — just show what would happen."""
        for i, p in enumerate(personas, 1):
            print(f"\n{'='*60}")
            print(f"[{i}] {p.name} ({p.user_id}) — Age {p.age}, {p.address.get('city', 'Unknown')}")
            print(f"    Email: {p.email}")
            for j, c in enumerate(p.conversations, 1):
                print(f"\n    Conversation {j}: {c.title}")
                for k, m in enumerate(c.messages, 1):
                    print(f"      {k}. {m}")
        print(f"\n{'='*60}")
        print("DRY RUN — no API calls were made.")

    def _print_summary(self, personas: list[UserPersona]):
        log.info(
            "\n{'='*60}\n"
            "=== GENERATION COMPLETE ===\n"
            "  Users created:    %d\n"
            "  Sessions created: %d\n"
            "  Messages sent:    %d\n"
            "  Errors:           %d\n"
            "{'='*60}",
            self.stats["users_created"],
            self.stats["sessions_created"],
            self.stats["messages_sent"],
            self.stats["errors"],
        )

        # Final data summary
        log.info("\nFinal data per user:")
        for p in personas:
            try:
                memories = self.client.get_memories(self.tenant_id, p.user_id)
                trips = self.client.get_trips(self.tenant_id, p.user_id)
                log.info(
                    "  %-20s  memories: %3d  trips: %2d",
                    p.name, len(memories), len(trips),
                )
            except Exception:
                log.info("  %-20s  (could not fetch stats)", p.name)

        # Post-processing: update trip statuses for a realistic mix
        self._update_trip_statuses(personas)

    def _update_trip_statuses(self, personas: list[UserPersona]):
        """Update some trips to confirmed/completed for realistic analytics."""
        log.info("\nUpdating trip statuses...")
        import random
        random.seed(42)

        all_trips = []
        for p in personas:
            try:
                trips = self.client.get_trips(self.tenant_id, p.user_id)
                for t in trips:
                    all_trips.append((p.user_id, t))
            except Exception:
                pass

        # Confirm trips that have day-by-day plans
        trips_with_days = [
            (uid, t) for uid, t in all_trips
            if t.get("days") and len(t["days"]) > 0 and t.get("status") == "planning"
        ]
        random.shuffle(trips_with_days)

        confirmed = 0
        completed = 0
        for i, (uid, t) in enumerate(trips_with_days):
            tid = t.get("tripId")
            if i < len(trips_with_days) // 2:
                new_status = "confirmed"
                confirmed += 1
            elif i < len(trips_with_days) // 2 + 2:
                new_status = "completed"
                completed += 1
            else:
                continue
            try:
                self.client.update_trip(self.tenant_id, uid, tid, {"status": new_status})
                log.info("  %s -> %s", t.get("destination", "?"), new_status)
            except Exception as e:
                log.warning("  Failed to update trip %s: %s", tid, e)

        log.info("  Updated: %d confirmed, %d completed", confirmed, completed)


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Generate realistic data for the Travel Multi-Agent analytics demo."
    )
    parser.add_argument(
        "--base-url", default=DEFAULT_BASE_URL,
        help=f"Base URL of the Travel API (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--tenant", default=DEFAULT_TENANT,
        help=f"Tenant ID for generated data (default: {DEFAULT_TENANT})",
    )
    parser.add_argument(
        "--personas", type=int, default=None,
        help="Limit to first N personas (default: all 12)",
    )
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY,
        help=f"Seconds delay between messages (default: {DEFAULT_DELAY})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the plan without making API calls",
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT,
        help=f"HTTP timeout per request in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--parallel", type=int, default=1,
        help="Run N personas concurrently (default: 1 = sequential). "
             "Recommended: 3-4 to cut runtime by 3-4x. Requires sufficient Azure OpenAI TPM.",
    )
    args = parser.parse_args()

    personas = PERSONAS[: args.personas] if args.personas else PERSONAS

    client = TravelAppClient(base_url=args.base_url, timeout=args.timeout)
    runner = DataGenerationRunner(
        client=client,
        tenant_id=args.tenant,
        delay=args.delay,
        dry_run=args.dry_run,
        parallel=args.parallel,
    )

    try:
        runner.run(personas)
    finally:
        client.close()


if __name__ == "__main__":
    main()
