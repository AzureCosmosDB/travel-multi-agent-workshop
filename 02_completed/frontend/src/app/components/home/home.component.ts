import { Component, OnInit, HostListener } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ChipComponent } from '../shared/chip/chip.component';
import { TravelApiService } from '../../services/travel-api.service';
import { City } from '../../models/travel.models';

@Component({
    selector: 'app-home',
    imports: [CommonModule, ChipComponent, FormsModule],
    templateUrl: './home.component.html',
    styleUrls: ['./home.component.css']
})
export class HomeComponent implements OnInit {
  trendingThemes = [
    'Street Photography',
    'Coffee Culture',
    'Family-Friendly',
    'Night Markets',
    'Local Cuisine',
    'Historic Sites'
  ];

  // Form fields
  selectedCity = '';
  startDate = '';
  endDate = '';
  travelers = {
    adults: 1,
    children: 0,
    pets: 0
  };

  // Autocomplete
  cities: City[] = [];
  filteredCities: City[] = [];
  showCityDropdown = false;
  isLoadingCities = false;

  // Pickers
  showDatePicker = false;
  showTravelersPicker = false;

  constructor(
    private router: Router,
    private travelApiService: TravelApiService
  ) {}

  ngOnInit(): void {
    this.loadCities();
  }

  loadCities(): void {
    this.isLoadingCities = true;
    this.travelApiService.getCities().subscribe({
      next: (cities) => {
        this.cities = cities;
        this.filteredCities = cities;
        this.isLoadingCities = false;
      },
      error: (error) => {
        console.error('Error loading cities:', error);
        this.isLoadingCities = false;
      }
    });
  }

  onCityInputChange(): void {
    if (!this.selectedCity) {
      this.filteredCities = this.cities;
      this.showCityDropdown = true;
      return;
    }

    const searchTerm = this.selectedCity.toLowerCase();
    this.filteredCities = this.cities.filter(city =>
      city.displayName.toLowerCase().includes(searchTerm) ||
      city.name.toLowerCase().includes(searchTerm)
    );
    this.showCityDropdown = true;
  }

  onCityFocus(): void {
    this.showCityDropdown = true;
  }

  onCityBlur(): void {
    // Delay to allow click on dropdown item
    setTimeout(() => {
      this.showCityDropdown = false;
    }, 200);
  }

  selectCity(city: City): void {
    this.selectedCity = city.displayName;
    this.showCityDropdown = false;
  }

  // Date Picker Methods
  toggleDatePicker(): void {
    this.showDatePicker = !this.showDatePicker;
    this.showTravelersPicker = false;
  }

  closeDatePicker(): void {
    this.showDatePicker = false;
  }

  getDateRangeDisplay(): string {
    if (!this.startDate && !this.endDate) {
      return 'Add dates';
    }
    if (this.startDate && !this.endDate) {
      return this.formatDate(this.startDate);
    }
    if (this.startDate && this.endDate) {
      return `${this.formatDate(this.startDate)} - ${this.formatDate(this.endDate)}`;
    }
    return 'Add dates';
  }

  private formatDate(dateString: string): string {
    if (!dateString) return '';
    // Parse as UTC to avoid timezone shifting
    const [year, month, day] = dateString.split('-').map(Number);
    const date = new Date(year, month - 1, day); // month is 0-indexed
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  // Travelers Picker Methods
  toggleTravelersPicker(): void {
    this.showTravelersPicker = !this.showTravelersPicker;
    this.showDatePicker = false;
  }

  closeTravelersPicker(): void {
    this.showTravelersPicker = false;
  }

  getTravelersDisplay(): string {
    const parts: string[] = [];
    
    if (this.travelers.adults > 0) {
      parts.push(`${this.travelers.adults} adult${this.travelers.adults !== 1 ? 's' : ''}`);
    }
    if (this.travelers.children > 0) {
      parts.push(`${this.travelers.children} child${this.travelers.children !== 1 ? 'ren' : ''}`);
    }
    if (this.travelers.pets > 0) {
      parts.push(`${this.travelers.pets} pet${this.travelers.pets !== 1 ? 's' : ''}`);
    }
    
    return parts.length > 0 ? parts.join(', ') : '1 adult';
  }

  incrementAdults(): void {
    if (this.travelers.adults < 10) {
      this.travelers.adults++;
    }
  }

  decrementAdults(): void {
    if (this.travelers.adults > 1) {
      this.travelers.adults--;
    }
  }

  incrementChildren(): void {
    if (this.travelers.children < 10) {
      this.travelers.children++;
    }
  }

  decrementChildren(): void {
    if (this.travelers.children > 0) {
      this.travelers.children--;
    }
  }

  incrementPets(): void {
    if (this.travelers.pets < 5) {
      this.travelers.pets++;
    }
  }

  decrementPets(): void {
    if (this.travelers.pets > 0) {
      this.travelers.pets--;
    }
  }

  startTrip(): void {
    if (!this.selectedCity) {
      alert('Please select a city first');
      return;
    }

    // Find the city object to get the actual city name (geoScopeId)
    const city = this.cities.find(c => 
      c.displayName === this.selectedCity || 
      c.name.toLowerCase() === this.selectedCity.toLowerCase()
    );

    if (city) {
      // Navigate to explore with the city
      this.router.navigate(['/explore'], { 
        queryParams: { city: city.name }
      });
    } else {
      this.router.navigate(['/explore']);
    }
  }

  exploreCities(): void {
    this.router.navigate(['/explore']);
  }

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    const target = event.target as HTMLElement;
    
    // Close dropdowns if clicking outside
    if (!target.closest('.relative')) {
      this.showCityDropdown = false;
      this.showDatePicker = false;
      this.showTravelersPicker = false;
    }
  }
}

