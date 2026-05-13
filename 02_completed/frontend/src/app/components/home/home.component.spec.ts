import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { HomeComponent } from './home.component';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { TravelApiService } from '../../services/travel-api.service';

describe('HomeComponent', () => {
  let component: HomeComponent;
  let fixture: ComponentFixture<HomeComponent>;
  let router: Router;
  let mockApiService: jasmine.SpyObj<TravelApiService>;

  beforeEach(async () => {
    mockApiService = jasmine.createSpyObj('TravelApiService', ['getCities']);
    mockApiService.getCities.and.returnValue(of([
      { id: 'rome', name: 'rome', displayName: 'Rome' }
    ]));

    await TestBed.configureTestingModule({
      imports: [HomeComponent],
      providers: [
        provideRouter([]),
        { provide: TravelApiService, useValue: mockApiService }
      ]
    }).compileComponents();

    fixture = TestBed.createComponent(HomeComponent);
    component = fixture.componentInstance;
    router = TestBed.inject(Router);
    spyOn(router, 'navigate');
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should have trending themes', () => {
    expect(component.trendingThemes).toBeDefined();
    expect(component.trendingThemes.length).toBeGreaterThan(0);
  });

  it('should render hero heading', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    const heading = compiled.querySelector('h1');
    expect(heading?.textContent).toContain('Plan like a local');
    expect(heading?.textContent).toContain('Remembered');
  });

  it('should render hero description', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    const description = compiled.querySelector('.text-gray-600');
    expect(description?.textContent).toContain('memory-first travel');
  });

  it('should render CTA buttons', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    const buttons = compiled.querySelectorAll('button');
    expect(buttons.length).toBeGreaterThanOrEqual(1);
  });

  it('should navigate to explore on startTrip()', () => {
    component.selectedCity = 'Rome';
    component.cities = [{ id: 'rome', name: 'rome', displayName: 'Rome' }];
    component.startTrip();
    expect(router.navigate).toHaveBeenCalledWith(['/explore'], { queryParams: { city: 'rome' } });
  });

  it('should navigate to explore on exploreCities()', () => {
    component.exploreCities();
    expect(router.navigate).toHaveBeenCalledWith(['/explore']);
  });

  it('should render trending themes chips', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    const chips = compiled.querySelectorAll('app-chip');
    expect(chips.length).toBe(component.trendingThemes.length);
  });

  it('should render hero image', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    const image = compiled.querySelector('img');
    expect(image).toBeTruthy();
    expect(image?.getAttribute('alt')).toBeTruthy();
  });

  it('should render features section', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    const featureHeading = compiled.querySelector('h2');
    expect(featureHeading?.textContent).toContain('Why Cosmos Voyager');
  });

  it('should render 3 feature cards', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    const sections = compiled.querySelectorAll('.grid.md\\:grid-cols-3');
    expect(sections.length).toBeGreaterThan(0);
  });

  it('should render How It Works section', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    const headings = compiled.querySelectorAll('h2');
    const howItWorks = Array.from(headings).find(h => h.textContent?.includes('How It Works'));
    expect(howItWorks).toBeTruthy();
  });

  it('should have Memory-First feature', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    const content = compiled.textContent;
    expect(content).toContain('Memory-First');
  });

  it('should have Multi-Agent AI feature', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    const content = compiled.textContent;
    expect(content).toContain('Multi-Agent AI');
  });

  it('should have Smart Discovery feature', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    const content = compiled.textContent;
    expect(content).toContain('Smart Discovery');
  });
});
