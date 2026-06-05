import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable, BehaviorSubject } from 'rxjs';
import { tap } from 'rxjs/operators';
import {
  Thread,
  Message,
  Place,
  Trip,
  Memory,
  ChatCompletionResponse,
  PlaceSearchRequest,
  User,
  City,
  PlaceFilterRequest
} from '../models/travel.models';

@Injectable({
  providedIn: 'root'
})
export class TravelApiService {
  private baseUrl = '/api';
  private defaultTenantId = 'marvel';
  private defaultUserId = 'tony';

  // User and city state management
  private currentUserSubject = new BehaviorSubject<User | null>(null);
  public currentUser$ = this.currentUserSubject.asObservable();

  private selectedCitySubject = new BehaviorSubject<string | null>(null);
  public selectedCity$ = this.selectedCitySubject.asObservable();

  // Thread state management
  private currentThreadSubject = new BehaviorSubject<Thread | null>(null);
  public currentThread$ = this.currentThreadSubject.asObservable();

  private messagesSubject = new BehaviorSubject<Message[]>([]);
  public messages$ = this.messagesSubject.asObservable();

  private threadsSubject = new BehaviorSubject<Thread[]>([]);
  public threads$ = this.threadsSubject.asObservable();

  constructor(private http: HttpClient) {
    // Try to load user from localStorage
    const savedUser = localStorage.getItem('currentUser');
    if (savedUser) {
      this.currentUserSubject.next(JSON.parse(savedUser));
    }
    
    // Load threads if user is logged in
    if (this.currentUserSubject.value) {
      this.loadThreads();
    }
  }

  private get tenantId(): string {
    return this.currentUserSubject.value?.tenantId || this.defaultTenantId;
  }

  // Public method to get tenantId
  getTenantId(): string {
    return this.tenantId;
  }

  private get userId(): string {
    return this.currentUserSubject.value?.userId || this.defaultUserId;
  }

  private getHeaders(): HttpHeaders {
    return new HttpHeaders({
      'Content-Type': 'application/json'
    });
  }

  // ============================================================================
  // Session Management (formerly Thread Management)
  // ============================================================================

  loadThreads(): void {
    this.http.get<Thread[]>(
      `${this.baseUrl}/tenant/${this.tenantId}/user/${this.userId}/sessions`,
      { headers: this.getHeaders() }
    ).subscribe({
      next: (threads) => this.threadsSubject.next(threads),
      error: (error) => console.error('Error loading sessions:', error)
    });
  }

  createThread(): Observable<Thread> {
    return this.http.post<Thread>(
      `${this.baseUrl}/tenant/${this.tenantId}/user/${this.userId}/sessions?activeAgent=orchestrator`,
      {},
      { headers: this.getHeaders() }
    ).pipe(
      tap(thread => {
        this.currentThreadSubject.next(thread);
        const threads = this.threadsSubject.value;
        this.threadsSubject.next([thread, ...threads]);
      })
    );
  }

  getThread(threadId: string): Observable<Thread> {
    return this.http.get<Thread>(
      `${this.baseUrl}/tenant/${this.tenantId}/user/${this.userId}/sessions/${threadId}`,
      { headers: this.getHeaders() }
    ).pipe(
      tap(thread => this.currentThreadSubject.next(thread))
    );
  }

  getThreadMessages(threadId: string): Observable<Message[]> {
    return this.http.get<Message[]>(
      `${this.baseUrl}/tenant/${this.tenantId}/user/${this.userId}/sessions/${threadId}/messages`,
      { headers: this.getHeaders() }
    ).pipe(
      tap(messages => this.messagesSubject.next(messages))
    );
  }

  renameThread(threadId: string, newTitle: string): Observable<Thread> {
    return this.http.patch<Thread>(
      `${this.baseUrl}/tenant/${this.tenantId}/user/${this.userId}/sessions/${threadId}/rename`,
      { title: newTitle },
      { headers: this.getHeaders() }
    );
  }

  deleteThread(threadId: string): Observable<any> {
    return this.http.delete(
      `${this.baseUrl}/tenant/${this.tenantId}/user/${this.userId}/sessions/${threadId}`,
      { headers: this.getHeaders() }
    ).pipe(
      tap(() => {
        const threads = this.threadsSubject.value.filter(t => (t.sessionId || t.threadId) !== threadId);
        this.threadsSubject.next(threads);
        const currentId = this.currentThreadSubject.value?.sessionId || this.currentThreadSubject.value?.threadId;
        if (currentId === threadId) {
          this.currentThreadSubject.next(null);
          this.messagesSubject.next([]);
        }
      })
    );
  }

  setCurrentThread(thread: Thread): void {
    this.currentThreadSubject.next(thread);
    if (thread) {
      const threadId = thread.sessionId || thread.threadId;
      if (threadId) {
        this.getThreadMessages(threadId).subscribe();
      }
    } else {
      this.messagesSubject.next([]);
    }
  }

  // ============================================================================
  // Chat Completion
  // ============================================================================

  sendMessage(threadId: string, message: string): Observable<any> {
    return this.http.post<any>(
      `${this.baseUrl}/tenant/${this.tenantId}/user/${this.userId}/sessions/${threadId}/completion`,
      JSON.stringify(message),
      { headers: this.getHeaders() }
    ).pipe(
      tap(response => {
        // Backend returns array of messages directly
        if (Array.isArray(response)) {
          const messages: Message[] = response.map((msg: any) => ({
            role: (msg.senderRole === 'User' ? 'user' : 'assistant') as 'user' | 'assistant' | 'system',
            content: msg.text || ''
          }));
          this.messagesSubject.next(messages);
        } else if (response.messages) {
          this.messagesSubject.next(response.messages);
        }
      })
    );
  }

  // ============================================================================
  // Places
  // ============================================================================

  searchPlaces(request: PlaceSearchRequest): Observable<Place[]> {
    console.log('🔍 Place search request:', request);
    return this.http.post<Place[]>(
      `${this.baseUrl}/places/search`,
      request,
      { headers: this.getHeaders() }
    );
  }

  // ============================================================================
  // Trips
  // ============================================================================

  getTrips(): Observable<Trip[]> {
    return this.http.get<Trip[]>(
      `${this.baseUrl}/tenant/${this.tenantId}/user/${this.userId}/trips`,
      { headers: this.getHeaders() }
    );
  }

  getTrip(tripId: string): Observable<Trip> {
    return this.http.get<Trip>(
      `${this.baseUrl}/tenant/${this.tenantId}/user/${this.userId}/trips/${tripId}`,
      { headers: this.getHeaders() }
    );
  }

  createTrip(trip: Partial<Trip>): Observable<Trip> {
    return this.http.post<Trip>(
      `${this.baseUrl}/tenant/${this.tenantId}/user/${this.userId}/trips`,
      trip,
      { headers: this.getHeaders() }
    );
  }

  updateTrip(tripId: string, trip: Partial<Trip>): Observable<Trip> {
    return this.http.put<Trip>(
      `${this.baseUrl}/tenant/${this.tenantId}/user/${this.userId}/trips/${tripId}`,
      trip,
      { headers: this.getHeaders() }
    );
  }

  deleteTrip(tripId: string): Observable<any> {
    return this.http.delete(
      `${this.baseUrl}/tenant/${this.tenantId}/user/${this.userId}/trips/${tripId}`,
      { headers: this.getHeaders() }
    );
  }

  // ============================================================================
  // Memories
  // ============================================================================

  getMemories(): Observable<Memory[]> {
    const url = `${this.baseUrl}/tenant/${this.tenantId}/user/${this.userId}/memories`;
    console.log('🔍 Fetching memories from:', url);
    return this.http.get<Memory[]>(url, { headers: this.getHeaders() }).pipe(
      tap(memories => console.log('✅ Memories response:', memories))
    );
  }

  createMemory(memory: Partial<Memory>): Observable<Memory> {
    return this.http.post<Memory>(
      `${this.baseUrl}/tenant/${this.tenantId}/user/${this.userId}/memories`,
      memory,
      { headers: this.getHeaders() }
    );
  }

  deleteMemory(memoryId: string): Observable<any> {
    return this.http.delete(
      `${this.baseUrl}/tenant/${this.tenantId}/user/${this.userId}/memories/${memoryId}`,
      { headers: this.getHeaders() }
    );
  }

  // ============================================================================
  // Health & Status
  // ============================================================================

  getHealthStatus(): Observable<any> {
    return this.http.get(`${this.baseUrl}/health/ready`, { headers: this.getHeaders() });
  }

  getSystemStatus(): Observable<any> {
    return this.http.get(`${this.baseUrl}/status`, { headers: this.getHeaders() });
  }

  // ============================================================================
  // User Management
  // ============================================================================

  setCurrentUser(user: User): void {
    this.currentUserSubject.next(user);
    localStorage.setItem('currentUser', JSON.stringify(user));
    // Reload threads for new user
    this.loadThreads();
  }

  getCurrentUser(): User | null {
    return this.currentUserSubject.value;
  }

  logout(): void {
    this.currentUserSubject.next(null);
    this.currentThreadSubject.next(null);
    this.messagesSubject.next([]);
    this.threadsSubject.next([]);
    localStorage.removeItem('currentUser');
  }

  getUsers(tenantId?: string): Observable<User[]> {
    const tenant = tenantId || this.defaultTenantId;
    return this.http.get<User[]>(
      `${this.baseUrl}/tenant/${tenant}/users`,
      { headers: this.getHeaders() }
    );
  }

  createUser(user: Partial<User>): Observable<User> {
    const userRequest = {
      userId: user.userId!,
      tenantId: this.tenantId,
      name: user.name!,
      gender: user.gender,
      age: user.age,
      phone: user.phone,
      address: user.address,
      email: user.email
    };

    return this.http.post<User>(
      `${this.baseUrl}/tenant/${this.tenantId}/users`,
      userRequest,
      { headers: this.getHeaders() }
    );
  }

  // ============================================================================
  // City Management
  // ============================================================================

  setSelectedCity(city: string): void {
    this.selectedCitySubject.next(city);
    localStorage.setItem('selectedCity', city);
  }

  getSelectedCity(): string | null {
    const saved = localStorage.getItem('selectedCity');
    if (saved) {
      this.selectedCitySubject.next(saved);
      return saved;
    }
    return this.selectedCitySubject.value;
  }

  getCities(): Observable<City[]> {
    return this.http.get<City[]>(
      `${this.baseUrl}/cities`,
      { headers: this.getHeaders() }
    );
  }

  // ============================================================================
  // Places - Filter (for UI)
  // ============================================================================

  filterPlaces(request: PlaceFilterRequest): Observable<Place[]> {
    const tenant = this.tenantId;
    console.log('🏢 Using tenant for filterPlaces:', tenant);
    console.log('🔍 Filter request being sent:', request);
    return this.http.post<Place[]>(
      `${this.baseUrl}/tenant/${tenant}/places/filter`,
      request,
      { headers: this.getHeaders() }
    );
  }
}

