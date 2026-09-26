import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute } from '@angular/router';
import { BehaviorSubject, of, Subject, throwError } from 'rxjs';
import { ExploreComponent } from './explore.component';
import { TravelApiService } from '../../services/travel-api.service';
import { City, Thread, Trip } from '../../models/travel.models';

describe('ExploreComponent Start a Trip', () => {
  let component: ExploreComponent;
  let fixture: ComponentFixture<ExploreComponent>;
  let api: jasmine.SpyObj<TravelApiService>;

  const city: City = { name: 'rome', displayName: 'Rome, Italy' } as City;
  const thread: Thread = {
    id: 'session-explore',
    sessionId: 'session-explore',
    tenantId: 'tenant',
    userId: 'user',
    title: 'New Conversation',
    createdAt: '2026-09-22T00:00:00Z'
  };
  const trip: Trip = {
    id: 'trip-explore',
    tripId: 'trip-explore',
    tenantId: 'tenant',
    userId: 'user',
    sessionId: 'session-explore',
    destination: 'Rome, Italy',
    startDate: '2026-10-10',
    endDate: '2026-10-14',
    status: 'planning',
    createdAt: '2026-09-22T00:00:00Z'
  };

  beforeEach(async () => {
    api = jasmine.createSpyObj(
      'TravelApiService',
      ['getCities', 'getThread', 'createThread', 'startTrip', 'filterPlaces', 'setSelectedCity'],
      {
        selectedCity$: new BehaviorSubject<string | null>(null),
        messages$: new BehaviorSubject([]),
        currentThread$: new BehaviorSubject<Thread | null>(null)
      }
    );
    api.getCities.and.returnValue(of([city]));
    api.getThread.and.returnValue(of(thread));
    api.createThread.and.returnValue(of(thread));
    api.startTrip.and.returnValue(of({ session: thread, trip }));
    api.filterPlaces.and.returnValue(of([]));

    await TestBed.configureTestingModule({
      imports: [ExploreComponent],
      providers: [
        { provide: TravelApiService, useValue: api },
        {
          provide: ActivatedRoute,
          useValue: {
            queryParams: of({
              city: 'rome',
              startDate: '2026-10-10',
              endDate: '2026-10-14',
              adults: '2',
              children: '1',
              pets: '1',
              sessionId: 'session-explore'
            })
          }
        }
      ]
    }).compileComponents();

    fixture = TestBed.createComponent(ExploreComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('restores Home selections and validates the exact routed session', () => {
    expect(component.selectedCity).toBe('Rome, Italy');
    expect(component.startDate).toBe('2026-10-10');
    expect(component.endDate).toBe('2026-10-14');
    expect(component.travelers).toEqual({ adults: 2, children: 1, pets: 1 });
    expect(api.getThread).toHaveBeenCalledWith('session-explore');
    expect(component.currentThread).toBe(thread);
  });

  it('cannot restart a trip after the routed session is bound', () => {
    api.filterPlaces.calls.reset();

    component.startTrip();

    expect(component.hasStartedTrip).toBeTrue();
    expect(api.startTrip).not.toHaveBeenCalled();
    const button: HTMLButtonElement = fixture.nativeElement.querySelector(
      'button[class*="w-full"][class*="bg-cosmos-primary"]'
    );
    expect(button.disabled).toBeTrue();
    expect(button.textContent).toContain('Trip started');
  });

  it('locks start trip while routed session restoration is pending', () => {
    const pending = new Subject<Thread>();
    api.getThread.and.returnValue(pending);
    api.startTrip.calls.reset();
    component.hasStartedTrip = false;

    component.ngOnInit();
    component.startTrip();
    fixture.detectChanges();

    expect(component.hasStartedTrip).toBeTrue();
    expect(api.startTrip).not.toHaveBeenCalled();
    const button: HTMLButtonElement = fixture.nativeElement.querySelector(
      'button[class*="w-full"][class*="bg-cosmos-primary"]'
    );
    expect(button.disabled).toBeTrue();
    expect(button.textContent).toContain('Trip started');
  });

  it('creates one in-place trip, retains requestId on retry, then locks the page state', () => {
    spyOn(window, 'alert');
    component.hasStartedTrip = false;
    component.currentThread = null;
    component['routeSessionId'] = null;
    api.filterPlaces.calls.reset();
    const pending = new Subject<{ session: Thread; trip: Trip }>();
    api.startTrip.and.returnValue(pending);

    component.startTrip();
    component.startTrip();

    expect(api.startTrip).toHaveBeenCalledTimes(1);
    const firstRequest = api.startTrip.calls.mostRecent().args[0];
    expect(firstRequest).toEqual(jasmine.objectContaining({
      requestId: jasmine.any(String),
      destination: 'Rome, Italy',
      startDate: '2026-10-10',
      endDate: '2026-10-14'
    }));
    fixture.detectChanges();
    const pendingButton = Array.from(
      fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>
    ).find(button => button.textContent?.includes('Starting trip'));
    expect(pendingButton?.disabled).toBeTrue();
    pending.error(new Error('network failed'));
    api.startTrip.and.returnValue(of({ session: thread, trip }));

    component.startTrip();

    expect(api.startTrip.calls.mostRecent().args[0].requestId).toBe(firstRequest.requestId);
    expect(api.filterPlaces).toHaveBeenCalledWith(jasmine.objectContaining({ city: 'rome' }));
    expect(api.setSelectedCity).toHaveBeenCalledWith('rome');
    expect(component.hasStartedTrip).toBeTrue();

    component.startTrip();
    expect(api.startTrip).toHaveBeenCalledTimes(2);
  });

  it('does not create a session or trip for invalid dates', () => {
    spyOn(window, 'alert');
    api.startTrip.calls.reset();
    component.hasStartedTrip = false;
    component['routeSessionId'] = null;
    component.startDate = '2026-10-14';
    component.endDate = '2026-10-10';

    component.startTrip();

    expect(api.startTrip).not.toHaveBeenCalled();
  });

  it('does not update places or selection when start-trip fails', () => {
    spyOn(window, 'alert');
    api.filterPlaces.calls.reset();
    api.setSelectedCity.calls.reset();
    component.hasStartedTrip = false;
    component['routeSessionId'] = null;
    api.startTrip.and.returnValue(throwError(() => new Error('trip write failed')));

    component.startTrip();

    expect(api.filterPlaces).not.toHaveBeenCalled();
    expect(api.setSelectedCity).not.toHaveBeenCalled();
    expect(window.alert).toHaveBeenCalledWith('Failed to start trip. Please try again.');
  });

  it('rejects a restored session whose identity does not match the route', () => {
    spyOn(window, 'alert');
    const mismatched = { ...thread, id: 'other', sessionId: 'other' };
    api.getThread.and.returnValue(of(mismatched));

    component.ngOnInit();
    component.openChat();

    expect(component.currentThread).toBeNull();
    expect(component.hasStartedTrip).toBeTrue();
    expect(api.createThread).not.toHaveBeenCalled();
    expect(api.startTrip).not.toHaveBeenCalled();
    expect(window.alert).toHaveBeenCalledWith(
      'Unable to restore this trip session. Please return home and start again.'
    );
  });

  it('keeps start trip locked when routed session restoration fails', () => {
    api.getThread.and.returnValue(throwError(() => new Error('not found')));
    api.startTrip.calls.reset();
    component.hasStartedTrip = false;

    component.ngOnInit();
    component.startTrip();

    expect(component.currentThread).toBeNull();
    expect(component.hasStartedTrip).toBeTrue();
    expect(api.startTrip).not.toHaveBeenCalled();
  });
});
