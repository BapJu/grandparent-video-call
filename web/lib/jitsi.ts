// Shared type for the Jitsi IFrame API, used by both the Pi's /kiosk page and
// the caller's EmbeddedCall. Declaring window.JitsiMeetExternalAPI in one place
// avoids conflicting global augmentations.

export type JitsiEmbedApi = {
  addListener: (event: string, handler: (payload: never) => void) => void;
  executeCommand: (command: string, ...args: unknown[]) => void;
  getNumberOfParticipants: () => number;
  isAudioMuted: () => Promise<boolean>;
  isVideoMuted: () => Promise<boolean>;
  dispose: () => void;
};

declare global {
  interface Window {
    JitsiMeetExternalAPI: new (domain: string, options: object) => JitsiEmbedApi;
  }
}
