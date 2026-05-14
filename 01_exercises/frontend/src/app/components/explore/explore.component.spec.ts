import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ExploreComponent } from './explore.component';
import { TravelApiService } from '../../services/travel-api.service';
import { BehaviorSubject, of } from 'rxjs';
import { ActivatedRoute } from '@angular/router';
import { City, Place, Thread } from '../../models/travel.models';

describe('ExploreComponent', () => {
  let component: ExploreComponent;
  let fixture: ComponentFixture<ExploreComponent>;
  let mockApiService: jasmine.SpyObj<TravelApiService>;
  let selectedCitySubject: BehaviorSubject<string | null>;
  let messagesSubject: BehaviorSubject<any[]>;
  let currentThreadSubject: BehaviorSubject<Thread | null>;

  const mockPlaces: Place[] = [
    {
      id: '1',
      name: 'Test Hotel',
      type: 'hotel',
      description: 'A great hotel',
      geoScopeId: 'rome',
      rating: 4.5,
      priceTier: 'upscale',
      tags: ['luxury', 'central'],
      accessibility: ['wheelchair-friendly']
    },
    {
      id: '2',
      name: 'Test Restaurant',
      type: 'restaurant',
      description: 'Amazing food',
      geoScopeId: 'rome',
      rating: 4.8,
      priceTier: 'moderate',
      tags: ['italian', 'outdoor-seating'],
      accessibility: []
    }
  ];

  const mockCities: City[] = [
    {
      id: 'amsterdam',
      name: 'amsterdam',
      displayName: 'Amsterdam, Netherlands'
    },
    {
      id: 'rome',
      name: 'rome',
      displayName: 'Rome, Italy'
    }
  ];

  beforeEach(async () => {
    spyOn(window, 'alert');
    selectedCitySubject = new BehaviorSubject<string | null>(null);
    messagesSubject = new BehaviorSubject<any[]>([]);
    currentThreadSubject = new BehaviorSubject<Thread | null>(null);

    mockApiService = jasmine.createSpyObj('TravelApiService', [
      'searchPlaces',
      'sendMessage',
      'filterPlaces',
      'getCities',
      'createThread',
      'getThreadMessages',
      'setSelectedCity'
    ], {
      selectedCity$: selectedCitySubject.asObservable(),
      messages$: messagesSubject.asObservable(),
      currentThread$: currentThreadSubject.asObservable()
    });
    mockApiService.searchPlaces.and.returnValue(of(mockPlaces));
    mockApiService.filterPlaces.and.returnValue(of(mockPlaces));
    mockApiService.getCities.and.returnValue(of(mockCities));
    mockApiService.createThread.and.returnValue(of({
      id: 'thread-1',
      sessionId: 'thread-1',
      threadId: 'thread-1',
      tenantId: 'test',
      userId: 'user1',
      title: 'Test',
      createdAt: new Date().toISOString()
    }));
    mockApiService.getThreadMessages.and.returnValue(of([]));
    mockApiService.sendMessage.and.returnValue(of({
      response: 'Hello! How can I help?',
      threadId: 'thread-1',
      messages: []
    }));

    await TestBed.configureTestingModule({
      imports: [ExploreComponent],
      providers: [
        { provide: TravelApiService, useValue: mockApiService },
        { provide: ActivatedRoute, useValue: { queryParams: of({}) } }
      ]
    }).compileComponents();

    fixture = TestBed.createComponent(ExploreComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should initialize with default filters', () => {
    expect(component.filters).toBeDefined();
    expect(component.filters.placeType).toBe('all');
    expect(component.filters.budget).toEqual([]);
  });

  it('should not load places until a city is selected', () => {
    expect(component.places.length).toBe(0);
  });

  it('should start trip when user types a city name without selecting from dropdown', () => {
    component.cities = mockCities;
    component.selectedCity = 'amsterdam';

    component.startTrip();

    expect(component.currentCityName).toBe('amsterdam');
    expect(mockApiService.filterPlaces).toHaveBeenCalledWith(
      jasmine.objectContaining({ city: 'amsterdam' })
    );
  });

  it('should load cities before starting trip if city list is not ready yet', () => {
    component.cities = [];
    component.selectedCity = 'amsterdam';

    component.startTrip();

    expect(mockApiService.getCities).toHaveBeenCalled();
    expect(component.currentCityName).toBe('amsterdam');
    expect(mockApiService.filterPlaces).toHaveBeenCalledWith(
      jasmine.objectContaining({ city: 'amsterdam' })
    );
  });

  it('should not reload places when selected city event matches current city', () => {
    component.cities = mockCities;
    component.currentCityName = 'amsterdam';
    mockApiService.filterPlaces.calls.reset();

    selectedCitySubject.next('amsterdam');

    expect(mockApiService.filterPlaces).not.toHaveBeenCalled();
  });

  it('should have chat closed by default', () => {
    expect(component.chatOpen).toBe(false);
  });

  it('should open and close chat', () => {
    component.openChat();
    expect(component.chatOpen).toBe(true);
    component.closeChat();
    expect(component.chatOpen).toBe(false);
  });

  it('should apply filters when applyFilters is called', () => {
    component.currentCityName = 'rome';
    component.filters.placeType = 'hotel';
    component.applyFilters();
    expect(mockApiService.filterPlaces).toHaveBeenCalledWith(
      jasmine.objectContaining({ city: 'rome', types: ['hotel'] })
    );
  });

  it('should reset filters', () => {
    component.currentCityName = 'rome';
    component.filters.placeType = 'hotel';
    component.filters.budget = ['luxury'];
    component.resetFilters();
    expect(component.filters.placeType).toBe('all');
    expect(component.filters.budget).toEqual([]);
  });

  it('should send chat message', () => {
    component.currentThread = { id: 'thread-1', sessionId: 'thread-1', threadId: 'thread-1', tenantId: 'test', userId: 'user1', title: 'Test', createdAt: new Date().toISOString() };
    component.newMessage = 'Show me hotels';
    component.sendMessage();
    expect(mockApiService.sendMessage).toHaveBeenCalled();
  });

  it('should clear chat input after sending message', () => {
    component.currentThread = { id: 'thread-1', sessionId: 'thread-1', threadId: 'thread-1', tenantId: 'test', userId: 'user1', title: 'Test', createdAt: new Date().toISOString(), lastMessageAt: new Date().toISOString() };
    component.newMessage = 'Show me hotels';
    component.sendMessage();
    expect(component.newMessage).toBe('');
  });

  it('should not send empty chat messages', () => {
    component.newMessage = '';
    component.sendMessage();
    expect(mockApiService.sendMessage).not.toHaveBeenCalled();
  });

  it('should add user message to chat on send', () => {
    mockApiService.sendMessage.and.returnValue(of([]));
    component.currentThread = { id: 'thread-1', sessionId: 'thread-1', threadId: 'thread-1', tenantId: 'test', userId: 'user1', title: 'Test', createdAt: new Date().toISOString(), lastMessageAt: new Date().toISOString() };
    component.newMessage = 'Show me hotels';
    const initialLength = component.messages.length;
    component.sendMessage();
    expect(component.messages.length).toBeGreaterThan(initialLength);
  });

  it('should handle save place action', () => {
    const place = mockPlaces[0];
    component.onSavePlace(place);
    // Should not throw error
    expect(component).toBeTruthy();
  });

  it('should handle add to day action', () => {
    const place = mockPlaces[0];
    component.onAddToDay(place);
    // Should not throw error
    expect(component).toBeTruthy();
  });

  it('should handle swap place action', () => {
    const place = mockPlaces[0];
    component.onSwapPlace(place);
    // Should not throw error
    expect(component).toBeTruthy();
  });

  it('should render filters sidebar', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.textContent).toContain('Filters');
  });

  it('should render place grid', () => {
    component.places = mockPlaces;
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    const cards = compiled.querySelectorAll('app-place-card');
    expect(cards.length).toBe(2);
  });

  it('should render chat FAB when chat is closed', () => {
    component.chatOpen = false;
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    const fab = compiled.querySelector('.fixed.right-4.bottom-24');
    expect(fab).toBeTruthy();
  });

  it('should show chat drawer when chat is open', () => {
    component.chatOpen = true;
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    const drawer = compiled.querySelector('.fixed.inset-0');
    expect(drawer).toBeTruthy();
  });
});
