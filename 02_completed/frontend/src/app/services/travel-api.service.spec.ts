import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TravelApiService } from './travel-api.service';
import { StartTripResponse, Thread, TravelPreferences, User } from '../models/travel.models';

describe('TravelApiService start-trip session state', () => {
  let service: TravelApiService;
  let http: HttpTestingController;

  const session: Thread = {
    id: 'session-1',
    sessionId: 'session-1',
    tenantId: 'marvel',
    userId: 'tony',
    title: 'New Conversation',
    createdAt: '2026-09-22T00:00:00Z'
  };

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        TravelApiService,
        provideHttpClient(),
        provideHttpClientTesting()
      ]
    });
    service = TestBed.inject(TravelApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    localStorage.clear();
  });

  it('commits the session only after the combined operation succeeds', () => {
    let current: Thread | null = null;
    service.currentThread$.subscribe(thread => current = thread);

    service.startTrip({
      requestId: 'attempt-123',
      destination: 'Rome, Italy',
      startDate: '2026-10-10',
      endDate: '2026-10-14'
    }).subscribe();

    expect(current).toBeNull();
    const request = http.expectOne('/api/tenant/marvel/user/tony/start-trip');
    expect(request.request.body.requestId).toBe('attempt-123');
    const response: StartTripResponse = {
      session,
      trip: {
        id: 'trip-1',
        tripId: 'trip-1',
        tenantId: 'marvel',
        userId: 'tony',
        sessionId: 'session-1',
        destination: 'Rome, Italy',
        startDate: '2026-10-10',
        endDate: '2026-10-14',
        status: 'planning',
        createdAt: '2026-09-22T00:00:00Z'
      }
    };
    request.flush(response);

    expect(current as Thread | null).toEqual(session);
  });

  it('does not commit a session when the combined operation fails', () => {
    let current: Thread | null = null;
    service.currentThread$.subscribe(thread => current = thread);

    service.startTrip({
      destination: 'Rome, Italy',
      startDate: '2026-10-10',
      endDate: '2026-10-14'
    }).subscribe({ error: () => undefined });

    http.expectOne('/api/tenant/marvel/user/tony/start-trip').flush(
      { detail: 'Failed to create trip' },
      { status: 500, statusText: 'Server Error' }
    );

    expect(current).toBeNull();
  });

  it('rejects a getThread response with a different session identity', () => {
    let error: Error | undefined;

    service.getThread('session-1').subscribe({
      error: value => error = value
    });
    http.expectOne('/api/tenant/marvel/user/tony/sessions/session-1').flush({
      ...session,
      id: 'session-other',
      sessionId: 'session-other'
    });

    expect(error?.message).toContain('Session identity mismatch');
  });

  it('loads the current profile using the active tenant and user', () => {
    const user: User = {
      id: 'tony',
      userId: 'tony',
      tenantId: 'marvel',
      name: 'Tony Stark',
      createdAt: '2025-01-15T10:00:00Z',
      preferences: { dietary: 'vegetarian' }
    };

    service.getUserProfile().subscribe(result => {
      expect(result.preferences?.dietary).toBe('vegetarian');
    });

    http.expectOne('/api/tenant/marvel/users/tony').flush(user);
    expect(service.getCurrentUser()?.preferences?.dietary).toBe('vegetarian');
  });

  it('persists preferences using the active tenant and user', () => {
    const preferences: TravelPreferences = {
      budget: 'luxury',
      mobility: 'car',
      dietary: 'vegetarian',
      timeOfDay: 'evening'
    };
    const user: User = {
      id: 'tony',
      userId: 'tony',
      tenantId: 'marvel',
      name: 'Tony Stark',
      createdAt: '2025-01-15T10:00:00Z',
      preferences
    };

    service.updatePreferences(preferences).subscribe();

    const request = http.expectOne('/api/tenant/marvel/users/tony/preferences');
    expect(request.request.method).toBe('PATCH');
    expect(request.request.body).toEqual({ preferences });
    request.flush(user);
    expect(service.getCurrentUser()?.preferences).toEqual(preferences);
  });
});
