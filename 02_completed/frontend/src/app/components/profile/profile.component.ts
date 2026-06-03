import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TravelApiService } from '../../services/travel-api.service';
import { Memory, UserSummary } from '../../models/travel.models';

@Component({
    selector: 'app-profile',
    imports: [CommonModule, FormsModule],
    templateUrl: './profile.component.html',
    styleUrls: ['./profile.component.css']
})
export class ProfileComponent implements OnInit {
  memories: Memory[] = [];
  userSummary: UserSummary | null = null;
  
  preferences = {
    budget: 'moderate',
    mobility: 'walk',
    dietary: 'any',
    timeOfDay: 'any'
  };

  constructor(private travelApi: TravelApiService) {}

  ngOnInit(): void {
    this.loadUserSummary();
    this.loadMemories();
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
    console.log('Saving preferences:', this.preferences);
    alert('Preferences saved! These will be used for future recommendations.');
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
