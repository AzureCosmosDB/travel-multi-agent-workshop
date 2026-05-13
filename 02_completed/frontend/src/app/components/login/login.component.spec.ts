import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { LoginComponent } from './login.component';
import { TravelApiService } from '../../services/travel-api.service';
import { of, throwError } from 'rxjs';
import { User } from '../../models/travel.models';
import { FormsModule } from '@angular/forms';

describe('LoginComponent', () => {
  let component: LoginComponent;
  let fixture: ComponentFixture<LoginComponent>;
  let mockTravelApiService: jasmine.SpyObj<TravelApiService>;
  let mockRouter: jasmine.SpyObj<Router>;

  const mockUsers: User[] = [
    {
      id: '1',
      userId: 'user1',
      tenantId: 'tenant1',
      name: 'User One',
      email: 'user1@example.com',
      createdAt: '2025-01-01T00:00:00Z'
    },
    {
      id: '2',
      userId: 'user2',
      tenantId: 'tenant1',
      name: 'User Two',
      email: 'user2@example.com',
      createdAt: '2025-01-01T00:00:00Z'
    }
  ];

  beforeEach(async () => {
    mockTravelApiService = jasmine.createSpyObj('TravelApiService', [
      'getUsers',
      'setCurrentUser',
      'createUser'
    ]);
    mockRouter = jasmine.createSpyObj('Router', ['navigate']);

    mockTravelApiService.getUsers.and.returnValue(of(mockUsers));

    await TestBed.configureTestingModule({
      imports: [LoginComponent, FormsModule],
      providers: [
        { provide: TravelApiService, useValue: mockTravelApiService },
        { provide: Router, useValue: mockRouter }
      ]
    }).compileComponents();

    fixture = TestBed.createComponent(LoginComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should load users on init', () => {
    expect(mockTravelApiService.getUsers).toHaveBeenCalled();
    expect(component.users).toEqual(mockUsers);
    expect(component.isLoading).toBeFalse();
  });

  it('should handle error when loading users', () => {
    const errorComponent = TestBed.createComponent(LoginComponent);
    mockTravelApiService.getUsers.and.returnValue(
      throwError(() => new Error('Failed to load users'))
    );
    
    errorComponent.componentInstance.ngOnInit();
    
    expect(errorComponent.componentInstance.errorMessage).toBe('Failed to load users. Please try again.');
    expect(errorComponent.componentInstance.isLoading).toBeFalse();
  });

  it('should select user and navigate to home', () => {
    component.selectedUserId = 'user1';
    component.onLogin();

    expect(mockTravelApiService.setCurrentUser).toHaveBeenCalledWith(mockUsers[0]);
    expect(mockRouter.navigate).toHaveBeenCalledWith(['/explore']);
  });

  it('should not navigate if no user selected', () => {
    component.selectedUserId = null;
    component.onUserSelect();

    expect(mockTravelApiService.setCurrentUser).not.toHaveBeenCalled();
    expect(mockRouter.navigate).not.toHaveBeenCalled();
  });

  it('should toggle create form', () => {
    expect(component.showCreateForm).toBeFalse();
    component.toggleCreateForm();
    expect(component.showCreateForm).toBeTrue();
    component.toggleCreateForm();
    expect(component.showCreateForm).toBeFalse();
  });

  it('should validate required fields before creating user', () => {
    component.newUser = {
      userId: '',
      name: 'Test User',
      email: 'test@example.com',
      phone: '',
      gender: '',
      age: undefined,
      address: { street: '', city: '', state: '', zip: '', country: '' }
    };

    component.createNewUser();

    expect(component.errorMessage).toBe('Please fill in all required fields (User ID, Name, Email)');
    expect(mockTravelApiService.createUser).not.toHaveBeenCalled();
  });

  it('should create new user successfully', () => {
    const newUser: User = {
      id: '3',
      userId: 'newuser',
      tenantId: 'tenant1',
      name: 'New User',
      email: 'new@example.com',
      createdAt: '2025-01-01T00:00:00Z'
    };

    component.newUser = {
      userId: 'newuser',
      name: 'New User',
      email: 'new@example.com',
      phone: '',
      gender: '',
      age: undefined,
      address: { street: '', city: '', state: '', zip: '', country: '' }
    };

    mockTravelApiService.createUser.and.returnValue(of(newUser));
    component.createNewUser();

    expect(mockTravelApiService.createUser).toHaveBeenCalled();
    expect(mockTravelApiService.setCurrentUser).toHaveBeenCalledWith(newUser);
    expect(mockRouter.navigate).toHaveBeenCalledWith(['/explore']);
  });

  it('should handle error when creating user', () => {
    component.newUser = {
      userId: 'newuser',
      name: 'New User',
      email: 'new@example.com',
      phone: '',
      gender: '',
      age: undefined,
      address: { street: '', city: '', state: '', zip: '', country: '' }
    };

    mockTravelApiService.createUser.and.returnValue(
      throwError(() => new Error('Failed to create user'))
    );
    component.createNewUser();

    expect(component.errorMessage).toBe('Failed to create user. Please try again.');
    expect(component.isLoading).toBeFalse();
    expect(mockRouter.navigate).not.toHaveBeenCalled();
  });

  it('should render login card', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    const card = compiled.querySelector('.bg-white.rounded-2xl');
    expect(card).toBeTruthy();
  });

  it('should render user dropdown', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    const select = compiled.querySelector('select');
    expect(select).toBeTruthy();
  });

  it('should render login button', () => {
    const compiled = fixture.nativeElement as HTMLElement;
    const buttons = compiled.querySelectorAll('button');
    const loginButton = Array.from(buttons).find(btn => btn.textContent?.includes('Login'));
    expect(loginButton).toBeTruthy();
  });

  it('should show create user form when toggled', () => {
    component.showCreateForm = true;
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    const form = compiled.querySelector('form');
    expect(form).toBeTruthy();
  });

  it('should display error message when error exists', () => {
    component.errorMessage = 'Test error message';
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    const errorDiv = compiled.querySelector('.bg-red-50');
    expect(errorDiv).toBeTruthy();
    expect(errorDiv?.textContent).toContain('Test error message');
  });

  it('should display loading state', () => {
    component.isLoading = true;
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    const loadingDiv = compiled.querySelector('.text-center.py-8');
    expect(loadingDiv).toBeTruthy();
    expect(loadingDiv?.textContent).toContain('Loading...');
  });

  it('should disable login button when no user selected', () => {
    component.selectedUserId = null;
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    const buttons = compiled.querySelectorAll('button');
    const loginButton = Array.from(buttons).find(btn => btn.textContent?.includes('Login')) as HTMLButtonElement;
    
    expect(loginButton.disabled).toBeTrue();
  });

  it('should enable login button when user selected', () => {
    component.selectedUserId = 'user1';
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    const buttons = compiled.querySelectorAll('button');
    const loginButton = Array.from(buttons).find(btn => btn.textContent?.includes('Login')) as HTMLButtonElement;
    
    expect(loginButton.disabled).toBeFalse();
  });
});
