import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MessageComponent } from './message.component';
import { Message } from '../../../models/travel.models';

describe('MessageComponent', () => {
  let component: MessageComponent;
  let fixture: ComponentFixture<MessageComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [MessageComponent]
    }).compileComponents();

    fixture = TestBed.createComponent(MessageComponent);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should display user message', () => {
    component.message = {
      role: 'user',
      content: 'Hello, I need help planning a trip'
    };
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.textContent).toContain('Hello, I need help planning a trip');
  });

  it('should display assistant message', () => {
    component.message = {
      role: 'assistant',
      content: 'I can help you with that!',
      metadata: { agent: 'Orchestrator' }
    };
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.textContent).toContain('I can help you with that!');
  });

  it('should display agent name for assistant messages', () => {
    component.message = {
      role: 'assistant',
      content: 'Here are some hotels',
      metadata: { agent: 'Hotel Agent' }
    };
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.textContent).toContain('Hotel Agent');
  });

  it('should apply different styling for user vs assistant', () => {
    // User message
    component.message = {
      role: 'user',
      content: 'User message'
    };
    fixture.detectChanges();
    let compiled = fixture.nativeElement as HTMLElement;
    let messageDiv = compiled.querySelector('.bg-black.text-white');
    expect(messageDiv).toBeTruthy();

    // Assistant message
    component.message = {
      role: 'assistant',
      content: 'Assistant message'
    };
    fixture.detectChanges();
    compiled = fixture.nativeElement as HTMLElement;
    messageDiv = compiled.querySelector('.bg-white');
    expect(messageDiv).toBeTruthy();
  });

  it('should render message content', () => {
    const content = 'This is a test message with some content';
    component.message = {
      role: 'user',
      content: content
    };
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.textContent).toContain(content);
  });

  it('should handle empty message content', () => {
    component.message = {
      role: 'user',
      content: ''
    };
    fixture.detectChanges();
    expect(component).toBeTruthy();
  });

  it('should render user avatar icon', () => {
    component.message = {
      role: 'user',
      content: 'Test'
    };
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.textContent).toContain('👤');
  });

  it('should render assistant avatar icon', () => {
    component.message = {
      role: 'assistant',
      content: 'Test'
    };
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.textContent).toContain('🤖');
  });
});
