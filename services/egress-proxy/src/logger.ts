/**
 * Egress Network and Audit Logger
 *
 * Implements PRD FR-022:
 * - Logs every allowed and denied request as an audit or network event.
 * - Records capsule, destination, timestamp, allow/deny decision, and policy reason.
 */

export interface EgressEvent {
  id: string;
  timestamp: string;
  capsuleId?: string;
  appKey: string;
  method: string;
  host: string;
  port: number;
  destinationIp?: string;
  decision: 'allowed' | 'denied';
  reason: string;
  bytesReceived?: number;
  bytesSent?: number;
}

export class EgressLogger {
  private events: EgressEvent[] = [];
  private listeners: ((event: EgressEvent) => void)[] = [];

  logEvent(event: Omit<EgressEvent, 'id' | 'timestamp'>): EgressEvent {
    const fullEvent: EgressEvent = {
      id: `egr-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,
      timestamp: new Date().toISOString(),
      ...event,
    };

    this.events.push(fullEvent);

    // Keep last 1000 events in memory
    if (this.events.length > 1000) {
      this.events.shift();
    }

    // Format console output
    const statusColor = fullEvent.decision === 'allowed' ? '\x1b[32m' : '\x1b[31m';
    const resetColor = '\x1b[0m';
    console.log(
      `[EGRESS] ${fullEvent.timestamp} [${fullEvent.appKey}] ${fullEvent.method} ${fullEvent.host}:${fullEvent.port} -> ${statusColor}${fullEvent.decision.toUpperCase()}${resetColor} (${fullEvent.reason})`
    );

    for (const listener of this.listeners) {
      try {
        listener(fullEvent);
      } catch {
        // ignore listener errors
      }
    }

    return fullEvent;
  }

  addListener(listener: (event: EgressEvent) => void): void {
    this.listeners.push(listener);
  }

  getEvents(filter?: { appKey?: string; decision?: 'allowed' | 'denied' }): EgressEvent[] {
    return this.events.filter((e) => {
      if (filter?.appKey && e.appKey !== filter.appKey) return false;
      if (filter?.decision && e.decision !== filter.decision) return false;
      return true;
    });
  }

  clear(): void {
    this.events = [];
  }
}
