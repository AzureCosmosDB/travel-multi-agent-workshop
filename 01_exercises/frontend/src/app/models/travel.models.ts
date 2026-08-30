export interface Thread {
  id: string;
  sessionId: string;  // Changed from threadId to match backend
  threadId?: string;  // Keep for backward compatibility
  tenantId: string;
  userId: string;
  title: string;
  activeAgent?: string;
  createdAt: string;
  lastMessageAt?: string;  // Made optional to match backend (lastActivityAt)
  lastActivityAt?: string;  // Added to match backend
  messageCount?: number;
}

export interface Message {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp?: string;
  metadata?: {
    agent?: string;
    toolCalls?: string[];
  };
}

export interface Place {
  id: string;
  geoScopeId: string;
  type: 'hotel' | 'restaurant' | 'activity';
  name: string;
  description: string;
  neighborhood?: string;
  rating?: number;
  priceTier?: 'budget' | 'moderate' | 'upscale' | 'luxury';
  tags?: string[];
  accessibility?: string[];
  hours?: { [key: string]: string };
  restaurantSpecific?: {
    cuisineTypes?: string[];
    dietaryOptions?: string[];
    seatingOptions?: string[];
  };
  hotelSpecific?: {
    amenities?: string[];
  };
  activitySpecific?: {
    ticketRequired?: boolean;
    duration?: string;
  };
}

export interface Trip {
  id: string;
  tripId: string;
  tenantId: string;
  userId: string;
  destination: string;
  startDate: string;
  endDate: string;
  status: 'planning' | 'confirmed' | 'completed';
  days?: TripDay[];
  createdAt: string;
}

export interface TripDay {
  dayNumber: number;
  date: string;
  morning?: TripActivity;
  lunch?: TripActivity;
  afternoon?: TripActivity;
  dinner?: TripActivity;
  evening?: TripActivity;
  accommodation?: TripActivity;
}

export interface TripActivity {
  activity: string;
  time?: string;
  placeId?: string;
  place?: Place;
}

export type MemoryType = 'turn' | 'summary' | 'fact' | 'user_summary' | 'procedural' | 'episodic';
export type MemoryRole = 'user' | 'agent' | 'tool' | 'system';

export interface Memory {
  id: string;
  user_id: string;
  thread_id?: string;
  role?: MemoryRole;
  type: MemoryType;
  content: string;
  metadata?: Record<string, any>;
  agent_id?: string;
  created_at?: string;
  updated_at?: string;
  tags?: string[];
  ttl?: number;
  salience?: number;
  content_hash?: string;
  superseded_by?: string;
  supersedes_ids?: string[];
  source_memory_ids?: string[];
  score?: number;
}

export interface UserSummary extends Memory {
  type: 'user_summary';
}

export interface ChatCompletionResponse {
  threadId: string;
  messages: Message[];
  activeAgent?: string;
}

export interface PlaceSearchRequest {
  geoScope: string;
  query: string;
  userId: string;
  tenantId?: string;
  filters?: {
    type?: string;
    priceTier?: string;
    dietary?: string[];
    accessibility?: string[];
    tags?: string[];
  };
}

export interface User {
  id: string;
  userId: string;
  tenantId: string;
  name: string;
  gender?: string;
  age?: number;
  phone?: string;
  address?: {
    street?: string;
    city?: string;
    state?: string;
    zip?: string;
    country?: string;
  };
  email?: string;
  createdAt: string;
}

export interface City {
  id: string;
  name: string;
  displayName: string;
}

export interface PlaceFilterRequest {
  city: string;
  types?: string[];
  priceTiers?: string[];
  dietary?: string[];
  accessibility?: string[];
  theme?: string;
}

