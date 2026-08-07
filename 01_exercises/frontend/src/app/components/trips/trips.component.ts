import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { TravelApiService } from '../../services/travel-api.service';
import { Trip } from '../../models/travel.models';

@Component({
    selector: 'app-trips',
    imports: [CommonModule],
    templateUrl: './trips.component.html',
    styleUrls: ['./trips.component.css']
})
export class TripsComponent implements OnInit {
  trips: Trip[] = [];
  selectedTrip: Trip | null = null;

  constructor(private travelApi: TravelApiService) {}

  ngOnInit(): void {
    this.loadTrips();
  }

  loadTrips(): void {
    this.travelApi.getTrips().subscribe({
      next: (trips) => {
        this.trips = trips;
      },
      error: (error) => {
        console.error('Error loading trips:', error);
        // Load mock data for demo
        this.loadMockTrips();
      }
    });
  }

  loadMockTrips(): void {
    this.trips = [
      {
        id: '1',
        tripId: 'trip-barcelona-2025',
        tenantId: 'demo',
        userId: 'demo',
        destination: 'Barcelona, Spain',
        startDate: '2025-11-01',
        endDate: '2025-11-05',
        status: 'planning',
        createdAt: '2025-10-20',
        days: [
          {
            dayNumber: 1,
            date: '2025-11-01',
            morning: { activity: 'Nømad Coffee Lab', time: '10:00-11:00' },
            lunch: { activity: 'Gothic Quarter Walk', time: '12:00-14:00' },
            afternoon: { activity: 'Sagrada Família', time: '15:00-17:00' },
            dinner: { activity: 'Cal Pep Tapas', time: '20:30-22:00' }
          },
          {
            dayNumber: 2,
            date: '2025-11-02',
            morning: { activity: 'Park Güell', time: '09:00-11:00' },
            lunch: { activity: 'La Boqueria Market', time: '12:30-13:30' },
            afternoon: { activity: 'Beach Walk', time: '15:00-17:00' },
            dinner: { activity: 'Tickets Bar', time: '21:00-23:00' }
          }
        ]
      },
      {
        id: '2',
        tripId: 'trip-rome-2025',
        tenantId: 'demo',
        userId: 'demo',
        destination: 'Rome, Italy',
        startDate: '2025-12-10',
        endDate: '2025-12-14',
        status: 'confirmed',
        createdAt: '2025-10-15'
      }
    ];
  }

  viewTrip(trip: Trip): void {
    this.selectedTrip = trip;
  }

  closeTrip(): void {
    this.selectedTrip = null;
  }

  confirmTrip(trip: Trip): void {
    this.travelApi.updateTrip(trip.tripId, { status: 'confirmed' }).subscribe({
      next: (updated) => {
        trip.status = updated?.status ?? 'confirmed';
        if (this.selectedTrip?.tripId === trip.tripId) {
          this.selectedTrip = { ...this.selectedTrip, status: trip.status };
        }
      },
      error: (error) => {
        console.error('Error confirming trip:', error);
        alert('Failed to confirm trip');
      }
    });
  }

  deleteTrip(trip: Trip): void {
    if (confirm(`Delete trip to ${trip.destination}?`)) {
      this.travelApi.deleteTrip(trip.tripId).subscribe({
        next: () => {
          this.trips = this.trips.filter(t => t.tripId !== trip.tripId);
          if (this.selectedTrip?.tripId === trip.tripId) {
            this.selectedTrip = null;
          }
          alert('Trip deleted successfully');
        },
        error: (error) => {
          console.error('Error deleting trip:', error);
          alert('Failed to delete trip');
        }
      });
    }
  }

  getStatusBadgeClass(status: string): string {
    switch (status) {
      case 'planning':
        return 'bg-yellow-100 text-yellow-800 border-yellow-200';
      case 'confirmed':
        return 'bg-green-100 text-green-800 border-green-200';
      case 'completed':
        return 'bg-gray-100 text-gray-800 border-gray-200';
      default:
        return 'bg-blue-100 text-blue-800 border-blue-200';
    }
  }

  formatDate(dateString: string): string {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  }
}
