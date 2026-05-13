import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { AppComponent } from './app.component';
import { provideRouter } from '@angular/router';
import { routes } from './app.routes';
import { TravelApiService } from './services/travel-api.service';
import { BehaviorSubject, of } from 'rxjs';
import { User } from './models/travel.models';

describe('AppComponent', () => {
  let component: AppComponent;
  let fixture: ComponentFixture<AppComponent>;
  let router: Router;
  let mockTravelApiService: jasmine.SpyObj<TravelApiService>;
  let currentUserSubject: BehaviorSubject<User | null>;

  const mockUser: User = {
    id: '1',
    userId: 'testuser',
    tenantId: 'tenant1',
    name: 'Test User',
    email: 'test@example.com',
    createdAt: '2025-01-01T00:00:00Z'
  };

  function setRouterUrl(url: string): void {
    Object.defineProperty(router, 'url', { value: url, configurable: true });
  }

  beforeEach(async () => {
    currentUserSubject = new BehaviorSubject<User | null>(null);
    
    mockTravelApiService = jasmine.createSpyObj('TravelApiService', [
      'logout'
    ], {
      currentUser$: currentUserSubject.asObservable()
    });

    await TestBed.configureTestingModule({
      imports: [AppComponent],
      providers: [
        provideRouter(routes),
        { provide: TravelApiService, useValue: mockTravelApiService }
      ]
    }).compileComponents();

    fixture = TestBed.createComponent(AppComponent);
    component = fixture.componentInstance;
    router = TestBed.inject(Router);
    fixture.detectChanges();
  });

  it('should create the app', () => {
    expect(component).toBeTruthy();
  });

  it('should have title "Cosmos Voyager"', () => {
    expect(component.title).toEqual('Cosmos Voyager');
  });

  it('should have navigation screens defined', () => {
    expect(component.screens).toBeDefined();
    expect(component.screens.length).toBe(3);
  });

  it('should contain explore screen', () => {
    const exploreScreen = component.screens.find(s => s.key === 'explore');
    expect(exploreScreen).toBeDefined();
    expect(exploreScreen?.label).toBe('Explore');
    expect(exploreScreen?.route).toBe('/explore');
  });

  it('should contain profile screen', () => {
    const profileScreen = component.screens.find(s => s.key === 'profile');
    expect(profileScreen).toBeDefined();
    expect(profileScreen?.label).toBe('Profile & Memories');
    expect(profileScreen?.route).toBe('/profile');
  });

  it('should contain trips screen', () => {
    const tripsScreen = component.screens.find(s => s.key === 'trips');
    expect(tripsScreen).toBeDefined();
    expect(tripsScreen?.label).toBe('My Trips');
    expect(tripsScreen?.route).toBe('/trips');
  });

  it('should subscribe to current user on init', () => {
    expect(component.currentUser).toBeNull();
    currentUserSubject.next(mockUser);
    expect(component.currentUser).toEqual(mockUser);
  });

  it('should redirect to login when no user and not on login page', (done) => {
    spyOn(router, 'navigate');
    setRouterUrl('/home');
    
    component.ngOnInit();
    currentUserSubject.next(null);
    
    setTimeout(() => {
      expect(router.navigate).toHaveBeenCalledWith(['/login']);
      done();
    }, 100);
  });

  it('should not redirect when on login page', () => {
    spyOn(router, 'navigate');
    setRouterUrl('/login');
    
    component.ngOnInit();
    currentUserSubject.next(null);
    
    expect(router.navigate).not.toHaveBeenCalled();
  });

  it('should logout and navigate to login', () => {
    spyOn(router, 'navigate');
    component.logout();
    
    expect(mockTravelApiService.logout).toHaveBeenCalled();
    expect(router.navigate).toHaveBeenCalledWith(['/login']);
  });

  it('should return true for isLoggedIn when user exists', () => {
    component.currentUser = mockUser;
    expect(component.isLoggedIn).toBeTrue();
  });

  it('should return false for isLoggedIn when no user', () => {
    component.currentUser = null;
    expect(component.isLoggedIn).toBeFalse();
  });

  it('should return true for isLoginPage when on login route', () => {
    setRouterUrl('/login');
    expect(component.isLoginPage).toBeTrue();
  });

  it('should return false for isLoginPage when not on login route', () => {
    setRouterUrl('/home');
    expect(component.isLoginPage).toBeFalse();
  });

  it('should hide top bar on login page', () => {
    setRouterUrl('/login');
    fixture.detectChanges();
    
    const compiled = fixture.nativeElement as HTMLElement;
    const topBar = compiled.querySelector('.top-0.z-40');
    // Top bar should not be rendered when isLoginPage is true
    expect(topBar).toBeFalsy();
  });

  it('should show user name when logged in', () => {
    currentUserSubject.next(mockUser);
    setRouterUrl('/home');
    fixture.detectChanges();
    
    const compiled = fixture.nativeElement as HTMLElement;
    const welcome = compiled.querySelector('.text-gray-600');
    expect(welcome?.textContent).toContain('Welcome, Test User');
  });

  it('should show logout button when logged in', () => {
    currentUserSubject.next(mockUser);
    setRouterUrl('/home');
    fixture.detectChanges();
    
    const compiled = fixture.nativeElement as HTMLElement;
    const logoutButton = compiled.querySelector('button.border-red-500');
    expect(logoutButton).toBeTruthy();
    expect(logoutButton?.textContent).toContain('Logout');
  });

  it('should hide navigation tabs when not logged in', () => {
    currentUserSubject.next(null);
    setRouterUrl('/home');
    fixture.detectChanges();
    
    const compiled = fixture.nativeElement as HTMLElement;
    const navTabs = compiled.querySelector('.top-16.z-30');
    expect(navTabs).toBeFalsy();
  });

  it('should have router outlet', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    const outlet = compiled.querySelector('router-outlet');
    expect(outlet).toBeTruthy();
  });

  it('should render footer', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    const footer = compiled.querySelector('footer');
    expect(footer?.textContent).toContain('© 2025 Cosmos Voyager');
  });
});
