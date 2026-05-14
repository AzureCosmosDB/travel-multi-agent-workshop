import { ComponentFixture, TestBed } from '@angular/core/testing';
import { PlaceCardComponent } from './place-card.component';
import { Place } from '../../../models/travel.models';

describe('PlaceCardComponent', () => {
  let component: PlaceCardComponent;
  let fixture: ComponentFixture<PlaceCardComponent>;

  const mockPlace: Place = {
    id: 'place-1',
    geoScopeId: 'barcelona',
    type: 'hotel',
    name: 'Hotel Barcelona',
    description: 'A wonderful hotel in the heart of Barcelona',
    neighborhood: 'Gothic Quarter',
    rating: 4.5,
    priceTier: 'moderate',
    tags: ['cozy', 'central', 'wifi']
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [PlaceCardComponent]
    }).compileComponents();

    fixture = TestBed.createComponent(PlaceCardComponent);
    component = fixture.componentInstance;
    component.place = mockPlace;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should display place name', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.textContent).toContain('Hotel Barcelona');
  });

  it('should display place description', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.textContent).toContain('A wonderful hotel in the heart of Barcelona');
  });

  it('should display place rating', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.textContent).toContain('4.5');
  });

  it('should display price tier', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.textContent).toContain('$$');
  });

  it('should display tags', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.textContent).toContain('cozy');
    expect(compiled.textContent).toContain('central');
  });

  it('should return the hotel icon for hotels', () => {
    expect(component.getIcon()).toBe('🏨');
  });

  it('should return a display value for the price tier', () => {
    expect(component.getPriceTierDisplay()).toBe('$$');
  });

  it('should not render action buttons', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    const buttons = compiled.querySelectorAll('button');
    expect(buttons.length).toBe(0);
  });

  it('should render chip components for tags', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    const chips = compiled.querySelectorAll('app-chip');
    expect(chips.length).toBe(mockPlace.tags!.length);
  });

  it('should display neighborhood if available', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.textContent).toContain('Gothic Quarter');
  });

  it('should handle place without rating', () => {
    const placeWithoutRating: Place = { ...mockPlace, rating: undefined };
    component.place = placeWithoutRating;
    fixture.detectChanges();
    expect(component).toBeTruthy();
  });

  it('should handle place without tags', () => {
    const placeWithoutTags: Place = { ...mockPlace, tags: undefined };
    component.place = placeWithoutTags;
    fixture.detectChanges();
    expect(component).toBeTruthy();
  });

  it('should render image placeholder', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    const imageDiv = compiled.querySelector('.h-20');
    expect(imageDiv).toBeTruthy();
  });
});
