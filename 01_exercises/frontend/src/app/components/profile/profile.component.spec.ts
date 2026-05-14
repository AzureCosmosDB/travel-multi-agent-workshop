import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ProfileComponent } from './profile.component';
import { TravelApiService } from '../../services/travel-api.service';
import { of } from 'rxjs';
import { Memory } from '../../models/travel.models';

describe('ProfileComponent', () => {
  let component: ProfileComponent;
  let fixture: ComponentFixture<ProfileComponent>;
  let mockApiService: jasmine.SpyObj<TravelApiService>;

  const mockMemories: Memory[] = [
    {
      id: 'mem-1',
      memoryId: 'mem-1',
      tenantId: 'test',
      userId: 'user1',
      memoryType: 'declarative',
      text: 'Favorite cuisine is Italian',
      facets: { category: 'dining', preference: 'Italian' },
      salience: 0.9,
      justification: 'User explicitly stated a cuisine preference',
      extractedAt: new Date().toISOString(),
      lastUsedAt: new Date().toISOString()
    },
    {
      id: 'mem-2',
      memoryId: 'mem-2',
      tenantId: 'test',
      userId: 'user1',
      memoryType: 'episodic',
      text: 'Visited Rome and Paris',
      facets: { category: 'hotel', cities: ['Rome', 'Paris'] },
      salience: 0.7,
      justification: 'User discussed previous trips',
      extractedAt: new Date().toISOString(),
      lastUsedAt: new Date().toISOString()
    }
  ];

  beforeEach(async () => {
    spyOn(window, 'alert');
    spyOn(window, 'confirm').and.returnValue(true);

    mockApiService = jasmine.createSpyObj('TravelApiService', [
      'getMemories',
      'createMemory',
      'deleteMemory'
    ]);
    mockApiService.getMemories.and.returnValue(of(mockMemories));
    mockApiService.deleteMemory.and.returnValue(of(void 0));

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
    expect(mockApiService.getMemories).toHaveBeenCalled();
    expect(component.memories.length).toBe(2);
  });

  it('should have default preferences', () => {
    expect(component.preferences).toBeDefined();
    expect(component.preferences.budget).toBe('moderate');
  });

  it('should save preferences', () => {
    component.savePreferences();
    // Should not throw error
    expect(component).toBeTruthy();
  });

  it('should delete memory', () => {
    const memory = mockMemories[0];
    component.deleteMemory(memory);
    expect(mockApiService.deleteMemory).toHaveBeenCalledWith(memory.memoryId);
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
