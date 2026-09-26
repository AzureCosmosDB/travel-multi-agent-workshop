import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ProfileComponent } from './profile.component';
import { TravelApiService } from '../../services/travel-api.service';
import { of, throwError } from 'rxjs';
import { Memory, User, UserSummary } from '../../models/travel.models';

describe('ProfileComponent', () => {
  let component: ProfileComponent;
  let fixture: ComponentFixture<ProfileComponent>;
  let mockApiService: jasmine.SpyObj<TravelApiService>;

  const mockMemories: Memory[] = [
    {
      id: 'mem-1',
      user_id: 'user1',
      thread_id: 'thread-1',
      role: 'system',
      type: 'fact',
      content: 'Favorite cuisine is Italian',
      metadata: { category: 'dining' },
      created_at: new Date().toISOString(),
      tags: ['dining'],
      salience: 0.8
    },
    {
      id: 'mem-2',
      user_id: 'user1',
      thread_id: 'thread-1',
      role: 'system',
      type: 'episodic',
      content: 'Visited Rome and Paris',
      metadata: { category: 'hotel' },
      created_at: new Date().toISOString(),
      tags: ['hotel']
    }
  ];

  const mockSummary: UserSummary = {
    id: 'summary-1',
    user_id: 'user1',
    thread_id: 'summary-thread',
    role: 'system',
    type: 'user_summary',
    content: 'User prefers walkable trips and Italian restaurants.',
    metadata: {},
    created_at: new Date().toISOString(),
    tags: []
  };

  const mockUser: User = {
    id: 'user1',
    userId: 'user1',
    tenantId: 'marvel',
    name: 'Test User',
    createdAt: new Date().toISOString(),
    preferences: {
      budget: 'moderate',
      mobility: 'walk',
      dietary: 'vegetarian',
      timeOfDay: 'any'
    }
  };

  beforeEach(async () => {
    mockApiService = jasmine.createSpyObj('TravelApiService', [
      'getUserId',
      'getUserProfile',
      'updatePreferences',
      'getMemories',
      'getUserSummary',
      'deleteMemory'
    ]);
    mockApiService.getUserId.and.returnValue('user1');
    mockApiService.getUserProfile.and.returnValue(of(mockUser));
    mockApiService.updatePreferences.and.returnValue(of(mockUser));
    mockApiService.getMemories.and.returnValue(of(mockMemories));
    mockApiService.getUserSummary.and.returnValue(of(mockSummary));
    mockApiService.deleteMemory.and.returnValue(of(void 0));

    spyOn(window, 'alert');
    spyOn(window, 'confirm').and.returnValue(true);

    await TestBed.configureTestingModule({
      imports: [ProfileComponent],
      providers: [
        { provide: TravelApiService, useValue: mockApiService }
      ]
    }).compileComponents();

    fixture = TestBed.createComponent(ProfileComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should load memories on init', () => {
    expect(mockApiService.getMemories).toHaveBeenCalledWith('user1');
    expect(component.memories.length).toBe(2);
  });

  it('should load user summary on init', () => {
    expect(mockApiService.getUserSummary).toHaveBeenCalledWith('user1');
    expect(component.userSummary).toEqual(mockSummary);
  });

  it('should have default preferences', () => {
    expect(component.preferences).toBeDefined();
    expect(component.preferences.budget).toBe('moderate');
  });

  it('should load persisted preferences', () => {
    expect(mockApiService.getUserProfile).toHaveBeenCalled();
    expect(component.preferences.dietary).toBe('vegetarian');
  });

  it('should save preferences through the API', () => {
    component.savePreferences();
    expect(mockApiService.updatePreferences).toHaveBeenCalledWith(component.preferences);
    expect(component.preferenceMessage).toBe('Preferences saved.');
    expect(component.preferenceError).toBe('');
  });

  it('should reload Tony as vegetarian after saving and reopening the profile', () => {
    component.preferences.dietary = 'vegetarian';
    component.savePreferences();
    fixture.destroy();

    mockApiService.getUserProfile.and.returnValue(of(mockUser));
    fixture = TestBed.createComponent(ProfileComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();

    expect(mockApiService.getUserProfile).toHaveBeenCalled();
    expect(component.preferences.dietary).toBe('vegetarian');
  });

  it('should surface save failures without reporting success', () => {
    mockApiService.updatePreferences.and.returnValue(
      throwError(() => new Error('Cosmos unavailable'))
    );

    component.savePreferences();

    expect(component.preferenceMessage).toBe('');
    expect(component.preferenceError).toBe('Failed to save preferences.');
  });

  it('should delete memory', () => {
    const memory = mockMemories[0];
    component.deleteMemory(memory);
    expect(mockApiService.deleteMemory).toHaveBeenCalledWith('user1', memory.id, memory.thread_id!);
  });

  it('should render preferences form', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    const selects = compiled.querySelectorAll('select');
    expect(selects.length).toBeGreaterThanOrEqual(4);
  });

  it('should render memories list', () => {
    component.memories = mockMemories;
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    const content = compiled.textContent;
    expect(content).toContain('Favorite cuisine is Italian');
  });

  it('should render user summary', () => {
    component.userSummary = mockSummary;
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.textContent).toContain('User prefers walkable trips');
  });

  it('should have save preferences button', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    const buttons = compiled.querySelectorAll('button');
    const saveButton = Array.from(buttons).find(b => b.textContent?.includes('Save'));
    expect(saveButton).toBeTruthy();
  });

  it('should render memory delete buttons', () => {
    component.memories = mockMemories;
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    const deleteButtons = compiled.querySelectorAll('button');
    expect(deleteButtons.length).toBeGreaterThan(0);
  });

  it('should display empty state when no memories', () => {
    component.memories = [];
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    const content = compiled.textContent;
    expect(content).toContain('No memories');
  });
});
