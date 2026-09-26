import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TravelApiService } from '../../services/travel-api.service';
import { Memory, TravelPreferences, UserSummary } from '../../models/travel.models';

@Component({
    selector: 'app-profile',
    imports: [CommonModule, FormsModule],
    templateUrl: './profile.component.html',
    styleUrls: ['./profile.component.css']
})
export class ProfileComponent implements OnInit {
  memories: Memory[] = [];
  userSummary: UserSummary | null = null;
  isSavingPreferences = false;
  preferenceMessage = '';
  preferenceError = '';
  
  preferences: TravelPreferences = {
    budget: 'moderate',
    mobility: 'walk',
    dietary: 'any',
    timeOfDay: 'any'
  };

  constructor(private travelApi: TravelApiService) {}

  ngOnInit(): void {
    this.loadPreferences();
    this.loadUserSummary();
    this.loadMemories();
  }

  loadPreferences(): void {
    this.travelApi.getUserProfile().subscribe({
      next: (user) => {
        this.preferences = {
          ...this.preferences,
          ...user.preferences
        };
        this.preferenceError = '';
      },
      error: (error) => {
        console.error('Error loading user preferences:', error);
        this.preferenceError = 'Failed to load preferences.';
      }
    });
  }

  loadUserSummary(): void {
    this.travelApi.getUserSummary(this.travelApi.getUserId()).subscribe({
      next: (summary) => {
        this.userSummary = summary;
      },
      error: (error) => {
        console.error('Error loading user summary:', error);
        this.userSummary = null;
      }
    });
  }

  loadMemories(): void {
    this.travelApi.getMemories(this.travelApi.getUserId()).subscribe({
      next: (memories) => {
        console.log('📝 Memories received:', memories);
        console.log('📝 Number of memories:', memories?.length);
        this.memories = memories;
      },
      error: (error) => {
        console.error('Error loading memories:', error);
      }
    });
  }

  savePreferences(): void {
    this.isSavingPreferences = true;
    this.preferenceMessage = '';
    this.preferenceError = '';
    this.travelApi.updatePreferences(this.preferences).subscribe({
      next: (user) => {
        this.preferences = {
          ...this.preferences,
          ...user.preferences
        };
        this.preferenceMessage = 'Preferences saved.';
        this.isSavingPreferences = false;
      },
      error: (error) => {
        console.error('Error saving preferences:', error);
        this.preferenceError = 'Failed to save preferences.';
        this.isSavingPreferences = false;
      }
    });
  }

  deleteMemory(memory: Memory): void {
    if (!memory.thread_id) {
      alert('Cannot delete this memory because it is missing a thread id.');
      return;
    }

    if (confirm(`Delete memory: ${memory.content}?`)) {
      this.travelApi.deleteMemory(this.travelApi.getUserId(), memory.id, memory.thread_id).subscribe({
        next: () => {
          this.memories = this.memories.filter(m => m.id !== memory.id);
          alert('Memory deleted successfully');
        },
        error: (error) => {
          console.error('Error deleting memory:', error);
          alert('Failed to delete memory');
        }
      });
    }
  }
}
