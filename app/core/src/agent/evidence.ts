export interface TimelineSegment {
  start: string;
  end: string;
  duration_s: number;
  app: string;
  title: string;
  url_domain?: string;
  foreground: boolean;
  visible_fraction: number;
  purpose_hint: "coding" | "project_tools" | "video" | "research" | "communication" | "browsing" | "system";
  ocr_snippet?: string;
}

export interface PackedTimelineEvidence {
  summary: {
    start: string;
    end: string;
    total_duration_s: number;
    segment_count: number;
    primary_purposes: string[];
  };
  segments: TimelineSegment[];
}

interface RawItem {
  timestamp: string;
  app: string;
  title: string;
  url?: string;
  foreground: boolean;
  visible_fraction: number;
  ocr: string;
}

export class EvidencePacker {
  public static extractDomain(urlStr?: string): string | undefined {
    if (!urlStr) return undefined;
    try {
      const parsed = new URL(urlStr);
      return parsed.hostname.replace(/^www\./, "");
    } catch {
      return undefined;
    }
  }

  public static inferPurpose(
    app: string,
    title: string,
    url?: string
  ): TimelineSegment["purpose_hint"] {
    const lowerApp = app.toLowerCase();
    const lowerTitle = title.toLowerCase();
    const domain = (this.extractDomain(url) || "").toLowerCase();

    // 1. Unified Project Tools
    if (
      lowerTitle.includes("enheduanna") ||
      lowerTitle.includes("memvision") ||
      lowerTitle.includes("antigravity") ||
      lowerApp.includes("antigravity")
    ) {
      return "project_tools";
    }

    // 2. Video & Media
    if (
      domain.includes("youtube.com") ||
      domain.includes("youtu.be") ||
      domain.includes("netflix.com") ||
      domain.includes("twitch.tv") ||
      domain.includes("primevideo.com") ||
      lowerTitle.includes("trailer") ||
      lowerTitle.includes("youtube") ||
      lowerApp.includes("vlc")
    ) {
      return "video";
    }

    // 3. Coding & Development
    if (
      lowerApp.includes("code") ||
      lowerApp.includes("devenv") ||
      lowerApp.includes("pycharm") ||
      lowerApp.includes("powershell") ||
      lowerApp.includes("wt.exe") ||
      lowerApp.includes("cmd.exe") ||
      lowerApp.includes("git") ||
      lowerTitle.includes(".ts") ||
      lowerTitle.includes(".js") ||
      lowerTitle.includes(".py") ||
      lowerTitle.includes(".json") ||
      lowerTitle.includes("visual studio")
    ) {
      return "coding";
    }

    // 4. Communication & Chat
    if (
      lowerApp.includes("discord") ||
      lowerApp.includes("slack") ||
      lowerApp.includes("teams") ||
      lowerApp.includes("telegram") ||
      lowerApp.includes("whatsapp") ||
      domain.includes("discord.com") ||
      domain.includes("slack.com")
    ) {
      return "communication";
    }

    // 5. Research & Documentation
    if (
      domain.includes("stackoverflow.com") ||
      domain.includes("github.com") ||
      domain.includes("wikipedia.org") ||
      domain.includes("google.com") ||
      domain.includes("docs.") ||
      lowerTitle.includes("documentation")
    ) {
      return "research";
    }

    // 6. System
    if (
      lowerApp.includes("explorer") ||
      lowerApp.includes("taskmgr") ||
      lowerApp.includes("systemsettings")
    ) {
      return "system";
    }

    return "browsing";
  }

  public static parseItems(toolResults: Array<{ name: string; content: string }>): RawItem[] {
    const rawItems: RawItem[] = [];

    for (const tr of toolResults) {
      let data: unknown;
      try {
        data = JSON.parse(tr.content);
      } catch {
        continue;
      }

      if (!data) continue;

      const candidates: unknown[] = Array.isArray(data)
        ? data
        : (data as any).results && Array.isArray((data as any).results)
          ? (data as any).results
          : (data as any).captures && Array.isArray((data as any).captures)
            ? (data as any).captures
            : [data];

      for (const c of candidates) {
        if (!c || typeof c !== "object") continue;
        const obj = c as Record<string, unknown>;

        // Capture or search record
        const ts = String(obj.timestamp || obj.start_time || "");
        if (!ts) continue;

        const app = String(obj.app_name || obj.app || "unknown");
        const title = String(obj.window_title || obj.title || "");
        const url = obj.url ? String(obj.url) : undefined;
        const fg = Boolean(obj.is_foreground ?? true);
        const vf = typeof obj.visible_fraction === "number" ? obj.visible_fraction : 1.0;
        const ocr = String(obj.ocr_text || obj.ocr || obj.full_ocr_text || "");

        rawItems.push({
          timestamp: ts,
          app,
          title,
          url,
          foreground: fg,
          visible_fraction: vf,
          ocr: ocr.replace(/\s+/g, " ").trim(),
        });

        // Also extract nested windows if present
        if (Array.isArray(obj.windows)) {
          for (const w of obj.windows) {
            if (!w || typeof w !== "object") continue;
            const wObj = w as Record<string, unknown>;
            const wApp = String(wObj.app_name || app);
            const wTitle = String(wObj.title || title);
            const wUrl = wObj.url ? String(wObj.url) : url;
            const wFg = Boolean(wObj.is_foreground ?? false);
            const wVf = typeof wObj.visible_fraction === "number" ? wObj.visible_fraction : 0.5;
            rawItems.push({
              timestamp: ts,
              app: wApp,
              title: wTitle,
              url: wUrl,
              foreground: wFg,
              visible_fraction: wVf,
              ocr: "",
            });
          }
        }
      }
    }

    // Sort chronologically
    return rawItems.sort(
      (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    );
  }

  public static packEvidence(
    toolResults: Array<{ name: string; content: string }>,
    query: string = ""
  ): PackedTimelineEvidence {
    const rawItems = this.parseItems(toolResults);
    const queryLower = query.toLowerCase();

    if (rawItems.length === 0) {
      return {
        summary: {
          start: "",
          end: "",
          total_duration_s: 0,
          segment_count: 0,
          primary_purposes: [],
        },
        segments: [],
      };
    }

    const mergedSegments: TimelineSegment[] = [];
    let current: TimelineSegment | null = null;
    let accumulatedOcr: string[] = [];

    for (const item of rawItems) {
      const itemTime = new Date(item.timestamp).getTime();
      const domain = this.extractDomain(item.url);
      const purpose = this.inferPurpose(item.app, item.title, item.url);

      if (
        current &&
        current.app === item.app &&
        current.title === item.title &&
        Math.abs(itemTime - new Date(current.end).getTime()) <= 30000 // within 30s gap
      ) {
        // Extend current segment
        current.end = item.timestamp;
        const dur = Math.max(
          2,
          Math.round((new Date(current.end).getTime() - new Date(current.start).getTime()) / 1000)
        );
        current.duration_s = dur;
        current.visible_fraction = Math.max(current.visible_fraction, item.visible_fraction);
        if (item.foreground) current.foreground = true;
        if (item.ocr && !accumulatedOcr.includes(item.ocr)) {
          accumulatedOcr.push(item.ocr);
        }
      } else {
        // Flush previous segment
        if (current) {
          if (accumulatedOcr.length > 0) {
            current.ocr_snippet = accumulatedOcr.join(" ").slice(0, 200);
          }
          mergedSegments.push(current);
        }

        // Start new segment
        accumulatedOcr = item.ocr ? [item.ocr] : [];
        current = {
          start: item.timestamp,
          end: item.timestamp,
          duration_s: 2, // baseline frame duration
          app: item.app,
          title: item.title,
          url_domain: domain,
          foreground: item.foreground,
          visible_fraction: item.visible_fraction,
          purpose_hint: purpose,
          ocr_snippet: item.ocr ? item.ocr.slice(0, 200) : undefined,
        };
      }
    }

    if (current) {
      if (accumulatedOcr.length > 0) {
        current.ocr_snippet = accumulatedOcr.join(" ").slice(0, 200);
      }
      mergedSegments.push(current);
    }

    // Filter out transient segments (< 3s) UNLESS they are explicitly mentioned in query
    const filteredSegments = mergedSegments.filter((seg) => {
      if (seg.duration_s >= 3) return true;
      const appKey = seg.app.toLowerCase().replace(/\.exe$/, "");
      const titleKey = seg.title.toLowerCase();
      if (queryLower.includes(appKey) || (titleKey && queryLower.includes(titleKey.slice(0, 10)))) {
        return true;
      }
      return false;
    });

    const overallStart = filteredSegments[0]?.start || rawItems[0].timestamp;
    const overallEnd =
      filteredSegments[filteredSegments.length - 1]?.end || rawItems[rawItems.length - 1].timestamp;
    const totalDuration = Math.max(
      0,
      Math.round((new Date(overallEnd).getTime() - new Date(overallStart).getTime()) / 1000)
    );

    const purposes = Array.from(new Set(filteredSegments.map((s) => s.purpose_hint)));

    return {
      summary: {
        start: overallStart,
        end: overallEnd,
        total_duration_s: totalDuration,
        segment_count: filteredSegments.length,
        primary_purposes: purposes,
      },
      segments: filteredSegments,
    };
  }
}
