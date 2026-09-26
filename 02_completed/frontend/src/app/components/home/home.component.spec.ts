import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { of, Subject, throwError } from 'rxjs';
import { HomeComponent } from './home.component';
import { TravelApiService } from '../../services/travel-api.service';
import { City, Thread, Trip } from '../../models/travel.models';

describe('HomeComponent Start a Trip', () => {
  let component: HomeComponent;
  let fixture: ComponentFixture<HomeComponent>;
  let router: jasmine.SpyObj<Router>;
  let api: jasmine.SpyObj<TravelApiService>;

  const city: City = { name: 'rome', displayName: 'Rome, Italy' } as City;
  const thread: Thread = {
    id: 'session-new',
    sessionId: 'session-new',
    tenantId: 'tenant',
    userId: 'user',
    title: 'New Conversation',
    createdAt: '2026-09-22T00:00:00Z'
  };
  const trip: Trip = {
    id: 'trip-new',
    tripId: 'trip-new',
    tenantId: 'tenant',
    userId: 'user',
    sessionId: 'session-new',
    destination: 'Rome, Italy',
    startDate: '2026-10-10',
    endDate: '2026-10-14',
    status: 'planning',
    createdAt: '2026-09-22T00:00:00Z'
  };

  beforeEach(async () => {
    router = jasmine.createSpyObj('Router', ['navigate']);
    api = jasmine.createSpyObj('TravelApiService', ['getCities', 'startTrip']);
    api.getCities.and.returnValue(of([city]));
    api.startTrip.and.returnValue(of({ session: thread, trip }));

    await TestBed.configureTestingModule({
      imports: [HomeComponent],
      providers: [
        { provide: Router, useValue: router },
        { provide: TravelApiService, useValue: api }
      ]
    }).compileComponents();

    fixture = TestBed.createComponent(HomeComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('creates and binds a trip before navigating while preserving selections', () => {
    component.selectedCity = city.displayName;
    component.startDate = '2026-10-10';
    component.endDate = '2026-10-14';
    component.travelers = { adults: 2, children: 1, pets: 1 };

    component.startTrip();

    expect(api.startTrip).toHaveBeenCalledWith(jasmine.objectContaining({
      requestId: jasmine.any(String),
      destination: 'Rome, Italy',
      startDate: '2026-10-10',
      endDate: '2026-10-14'
    }));
    expect(router.navigate).toHaveBeenCalledWith(['/explore'], {
      queryParams: {
        city: 'rome',
        startDate: '2026-10-10',
        endDate: '2026-10-14',
        adults: 2,
        children: 1,
        pets: 1,
        sessionId: 'session-new'
      }
    });
  });

  it('creates no records when dates are missing, invalid, or reversed', () => {
    spyOn(window, 'alert');
    component.selectedCity = city.displayName;

    for (const [startDate, endDate] of [
      ['', '2026-10-14'],
      ['2026-02-30', '2026-03-02'],
      ['2026-10-14', '2026-10-10']
    ]) {
      component.startDate = startDate;
      component.endDate = endDate;
      component.startTrip();
    }

    expect(api.startTrip).not.toHaveBeenCalled();
    expect(router.navigate).not.toHaveBeenCalled();
  });

  it('does not navigate or commit route state when start-trip fails', () => {
    spyOn(window, 'alert');
    api.startTrip.and.returnValue(throwError(() => new Error('trip write failed')));
    component.selectedCity = city.displayName;
    component.startDate = '2026-10-10';
    component.endDate = '2026-10-14';

    component.startTrip();

    expect(router.navigate).not.toHaveBeenCalled();
    expect(window.alert).toHaveBeenCalledWith('Failed to start trip. Please try again.');
  });

  it('coalesces rapid calls and retains the requestId for a retry', () => {
    spyOn(window, 'alert');
    const pending = new Subject<{ session: Thread; trip: Trip }>();
    api.startTrip.and.returnValue(pending);
    component.selectedCity = city.displayName;
    component.startDate = '2026-10-10';
    component.endDate = '2026-10-14';

    component.startTrip();
    component.startTrip();

    expect(api.startTrip).toHaveBeenCalledTimes(1);
    const firstRequest = api.startTrip.calls.mostRecent().args[0];
    expect(component.isStartingTrip).toBeTrue();
    fixture.detectChanges();
    const pendingButton = Array.from(
      fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>
    ).find(button => button.textContent?.includes('Starting trip'));
    expect(pendingButton?.disabled).toBeTrue();

    pending.error(new Error('network failed'));
    api.startTrip.and.returnValue(of({ session: thread, trip }));
    component.startTrip();

    const retryRequest = api.startTrip.calls.mostRecent().args[0];
    expect(retryRequest.requestId).toBe(firstRequest.requestId);
    expect(api.startTrip).toHaveBeenCalledTimes(2);
  });
});
