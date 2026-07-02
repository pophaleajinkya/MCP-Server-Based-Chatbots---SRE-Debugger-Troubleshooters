/**
 * Tests for src/components/views/OperationsView.tsx
 *
 * Key behaviors:
 * - On mount, both incidents AND change requests are fetched automatically.
 * - A single shared "hours" input (default 24) controls both fetches.
 * - Apply/Refresh re-fetches BOTH tabs simultaneously.
 * - Tab switcher buttons labelled "Incidents" and "Change Requests" switch the view.
 * - CR API response shape: { crqs: [...] }
 */

import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { OperationsView } from "@/components/views/OperationsView";

// ─── Response helpers ─────────────────────────────────────────────────────────

function okResponse(body: unknown): Promise<Response> {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  } as Response);
}

function errResponse(): Promise<Response> {
  return Promise.resolve({
    ok: false,
    status: 500,
    text: () => Promise.resolve("Server Error"),
    json: () => Promise.resolve(null),
  } as unknown as Response);
}

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const THIRTY_MIN_AGO = new Date(Date.now() - 30 * 60 * 1000).toISOString();

/** A well-formed incident with all relevant fields populated. */
const BASE_INC = {
  incidentNumber:            "INC0012345",
  priority:                  "2 - High",
  isMajorIncident:           "true",
  assignmentGroupDirectorId: "john.doe",
  openedAt:                  THIRTY_MIN_AGO,
  shortDescription:          "Production server is down",
  workNotes:                 JSON.stringify({
    "2026-03-24 10:00:00": "Investigating the issue.\nTeam has been notified.",
  }),
  state: "In Progress",
};

const INC_SPANISH_PRIORITY = {
  ...BASE_INC,
  incidentNumber:   "INC0011111",
  priority:         "4 - bajo",
  shortDescription: "Low priority — Spanish label",
  workNotes:        "—",
};

const INC_CHINESE_PRIORITY = {
  ...BASE_INC,
  incidentNumber:   "INC0022222",
  priority:         "4 - 低",
  shortDescription: "Low priority — Chinese label",
  workNotes:        "—",
};

const INC_NON_MAJOR = {
  ...BASE_INC,
  incidentNumber:   "INC0055555",
  isMajorIncident:  "false",
  shortDescription: "Non-major incident",
  workNotes:        "—",
};

const INC_EMPTY_NOTES = {
  ...BASE_INC,
  incidentNumber:   "INC0066666",
  shortDescription: "Incident with no notes",
  workNotes:        "",
};

/** A well-formed change request matching current API shape. */
const BASE_CR = {
  crqNumber:        "CRQ001234",
  state:            "Implement",
  shortDescription: "Deploy new microservice",
  assignmentGroup:  "Platform Team",
  plannedStartDate: new Date(Date.now() + 3_600_000).toISOString(),
  plannedEndDate:   new Date(Date.now() + 7_200_000).toISOString(),
};

/** API wraps CRs in { crqs: [...] } */
function crResponse(crs: unknown[]) {
  return okResponse({ crqs: crs });
}

// ─── Helper: render with auto-fetch mocked ────────────────────────────────────
// On mount OperationsView fetches BOTH incidents and CRs.
// Provide two mock responses: first for incidents, second for CRs.
function renderWithAutoFetch(fetchMock: jest.Mock, incRes = okResponse([]), crRes = okResponse({ crqs: [] })) {
  fetchMock
    .mockReturnValueOnce(incRes)   // incidents (auto-fetch)
    .mockReturnValueOnce(crRes);   // CRs (auto-fetch)
}

// ─── Suite ────────────────────────────────────────────────────────────────────

describe("OperationsView", () => {
  let fetchMock: jest.Mock;

  beforeEach(() => {
    fetchMock = jest.fn();
    global.fetch = fetchMock;
    jest.spyOn(console, "log").mockImplementation(() => {});
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: jest.fn().mockResolvedValue(undefined) },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  // ── Initial render ──────────────────────────────────────────────────────────

  it("renders the Operations page header", async () => {
    renderWithAutoFetch(fetchMock);
    render(<OperationsView />);
    await act(async () => {});
    expect(screen.getByText("Operations")).toBeInTheDocument();
  });

  it("shows the Apply button and Incidents tab by default", async () => {
    renderWithAutoFetch(fetchMock);
    render(<OperationsView />);
    await act(async () => {});
    expect(screen.getByRole("button", { name: "Apply" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Incidents/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Change Requests/i })).toBeInTheDocument();
  });

  it("renders Hours number input with default value 24", async () => {
    renderWithAutoFetch(fetchMock);
    render(<OperationsView />);
    await act(async () => {});
    expect(screen.getByText("Hours")).toBeInTheDocument();
    const numberInput = document.querySelector('input[type="number"]');
    expect(numberInput).toBeInTheDocument();
    expect(numberInput).toHaveValue(24);
  });

  // ── Tab navigation ──────────────────────────────────────────────────────────

  it("switches to Change Requests tab when Change Requests button is clicked", async () => {
    renderWithAutoFetch(fetchMock);
    render(<OperationsView />);
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: /^Change Requests/i }));
    // Shared hoursAgo stays at 24
    const numberInput = document.querySelector('input[type="number"]') as HTMLInputElement;
    expect(numberInput).toHaveValue(24);
  });

  it("switches back to the Incidents tab from Change Requests", async () => {
    renderWithAutoFetch(fetchMock);
    render(<OperationsView />);
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: /^Change Requests/i }));
    fireEvent.click(screen.getByRole("button", { name: /^Incidents/i }));
    const numberInput = document.querySelector('input[type="number"]') as HTMLInputElement;
    expect(numberInput).toHaveValue(24);
  });

  // ── Incidents — fetch lifecycle ─────────────────────────────────────────────

  it("auto-fetches incidents on mount", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([BASE_INC]))
      .mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText("INC0012345")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith("/api/operations/incidents?hours_ago=24");
  });

  it("sends GET to /api/operations/incidents?hours_ago=24 when Apply is clicked", async () => {
    // Auto-fetch on mount
    fetchMock
      .mockReturnValueOnce(okResponse([]))
      .mockReturnValueOnce(okResponse({ crqs: [] }))
      // Apply click re-fetches both
      .mockReturnValueOnce(okResponse([BASE_INC]))
      .mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await act(async () => {});
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/operations/incidents?hours_ago=24");
  });

  it("renders incident number, assigned-to, and summary after a successful fetch", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([BASE_INC]))
      .mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText("INC0012345")).toBeInTheDocument());
    expect(screen.getByText("john.doe")).toBeInTheDocument();
    expect(screen.getByText("Production server is down")).toBeInTheDocument();
  });

  it("shows an error state when the incidents API returns a non-OK status", async () => {
    fetchMock
      .mockReturnValueOnce(errResponse())
      .mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText("Error")).toBeInTheDocument());
  });

  // ── Priority normalization ──────────────────────────────────────────────────

  it("translates Spanish priority '4 - bajo' to the English badge '4 - Low'", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([INC_SPANISH_PRIORITY]))
      .mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText("4 - Low")).toBeInTheDocument());
    expect(screen.queryByText("4 - bajo")).not.toBeInTheDocument();
  });

  it("translates Chinese priority '4 - 低' to the English badge '4 - Low'", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([INC_CHINESE_PRIORITY]))
      .mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText("4 - Low")).toBeInTheDocument());
    expect(screen.queryByText("4 - 低")).not.toBeInTheDocument();
  });

  // ── isMajorIncident badge ───────────────────────────────────────────────────

  it("renders a 'Yes' badge for a major incident", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([BASE_INC]))
      .mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getAllByText("Yes").length).toBeGreaterThan(0));
  });

  it("renders a 'No' badge for a non-major incident", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([INC_NON_MAJOR]))
      .mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getAllByText("No").length).toBeGreaterThan(0));
  });

  // ── Work Notes modal ────────────────────────────────────────────────────────

  it("opens the Work Notes modal with parsed content when View is clicked", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([BASE_INC]))
      .mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText("View")).toBeInTheDocument());
    fireEvent.click(screen.getByText("View"));
    expect(screen.getByText("Work Notes")).toBeInTheDocument();
    expect(screen.getByText(/investigating the issue/i)).toBeInTheDocument();
  });

  it("closes the Work Notes modal when the backdrop overlay is clicked", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([BASE_INC]))
      .mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => fireEvent.click(screen.getByText("View")));
    expect(screen.getByText("Work Notes")).toBeInTheDocument();
    fireEvent.click(document.querySelector("div.fixed.inset-0") as HTMLElement);
    expect(screen.queryByText("Work Notes")).not.toBeInTheDocument();
  });

  it("shows a fallback message in the modal when work notes are blank", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([INC_EMPTY_NOTES]))
      .mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText("View")).toBeInTheDocument());
    fireEvent.click(screen.getByText("View"));
    expect(screen.getByText(/no work notes recorded for this incident/i)).toBeInTheDocument();
  });

  // ── Summary modal ───────────────────────────────────────────────────────────

  it("opens the Full Summary modal when the info icon is clicked", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([BASE_INC]))
      .mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByTitle("View full summary")).toBeInTheDocument());
    fireEvent.click(screen.getByTitle("View full summary"));
    expect(screen.getByText("Full Summary")).toBeInTheDocument();
    expect(screen.getAllByText("Production server is down").length).toBeGreaterThanOrEqual(1);
  });

  // ── Inline search ───────────────────────────────────────────────────────────

  it("renders the inline search input in the header", async () => {
    renderWithAutoFetch(fetchMock);
    render(<OperationsView />);
    await act(async () => {});
    expect(screen.getByPlaceholderText(/search all columns/i)).toBeInTheDocument();
  });

  it("filters incidents by search term after typing in the inline search box", async () => {
    const inc2 = { ...BASE_INC, incidentNumber: "INC0099999", shortDescription: "Disk full" };
    fetchMock
      .mockReturnValueOnce(okResponse([BASE_INC, inc2]))
      .mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText("INC0012345")).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText(/search all columns/i), {
      target: { value: "INC0099999" },
    });
    expect(screen.getByText("INC0099999")).toBeInTheDocument();
    expect(screen.queryByText("INC0012345")).not.toBeInTheDocument();
  });

  // ── Change Requests — fetch lifecycle ───────────────────────────────────────

  it("auto-fetches change requests on mount", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([]))
      .mockReturnValueOnce(crResponse([BASE_CR]));
    render(<OperationsView />);
    fireEvent.click(screen.getByRole("button", { name: /^Change Requests/i }));
    await waitFor(() => expect(screen.getByText("CRQ001234")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith("/api/operations/change-requests?hours_ago=24");
  });

  it("sends GET to both endpoints when Apply is clicked", async () => {
    // mount auto-fetch
    fetchMock
      .mockReturnValueOnce(okResponse([]))
      .mockReturnValueOnce(okResponse({ crqs: [] }))
      // Apply re-fetch
      .mockReturnValueOnce(okResponse([]))
      .mockReturnValueOnce(crResponse([BASE_CR]));
    render(<OperationsView />);
    await act(async () => {});
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/operations/incidents?hours_ago=24");
    expect(fetchMock).toHaveBeenCalledWith("/api/operations/change-requests?hours_ago=24");
  });

  it("renders the CRQ number and description after a successful fetch", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([]))
      .mockReturnValueOnce(crResponse([BASE_CR]));
    render(<OperationsView />);
    fireEvent.click(screen.getByRole("button", { name: /^Change Requests/i }));
    await waitFor(() => expect(screen.getByText("CRQ001234")).toBeInTheDocument());
    expect(screen.getByText("Deploy new microservice")).toBeInTheDocument();
  });

  it("shows an error state when the change-requests API returns a non-OK status", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([]))
      .mockReturnValueOnce(errResponse());
    render(<OperationsView />);
    fireEvent.click(screen.getByRole("button", { name: /^Change Requests/i }));
    await waitFor(() => expect(screen.getByText("Error")).toBeInTheDocument());
  });

  it("renders the Implement State badge for a change request", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([]))
      .mockReturnValueOnce(crResponse([BASE_CR]));
    render(<OperationsView />);
    fireEvent.click(screen.getByRole("button", { name: /^Change Requests/i }));
    await waitFor(() => expect(screen.getAllByText("Implement").length).toBeGreaterThan(0));
    // Verify at least one is a badge span (not just the filter option)
    const badge = screen.getAllByText("Implement").find(el => el.tagName === "SPAN");
    expect(badge).toBeTruthy();
  });

  // ── timeAgo display ─────────────────────────────────────────────────────────

  it("shows 'seconds ago' for an incident opened less than a minute ago", async () => {
    const inc = { ...BASE_INC, incidentNumber: "INC0071111", openedAt: new Date(Date.now() - 30_000).toISOString() };
    fetchMock.mockReturnValueOnce(okResponse([inc])).mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText(/\d+ seconds? ago/)).toBeInTheDocument());
  });

  it("shows 'minutes ago' for an incident opened between 1 and 59 minutes ago", async () => {
    const inc = { ...BASE_INC, incidentNumber: "INC0072222", openedAt: new Date(Date.now() - 45 * 60_000).toISOString() };
    fetchMock.mockReturnValueOnce(okResponse([inc])).mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText(/\d+ minutes? ago/)).toBeInTheDocument());
  });

  it("shows 'days ago' for an incident opened more than 24 hours ago", async () => {
    const inc = { ...BASE_INC, incidentNumber: "INC0073333", openedAt: new Date(Date.now() - 3 * 24 * 3_600_000).toISOString() };
    fetchMock.mockReturnValueOnce(okResponse([inc])).mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText(/\d+ days? ago/)).toBeInTheDocument());
  });

  it("shows a locale date string for an incident older than 30 days", async () => {
    const inc = { ...BASE_INC, incidentNumber: "INC0074444", openedAt: new Date(Date.now() - 40 * 24 * 3_600_000).toISOString() };
    fetchMock.mockReturnValueOnce(okResponse([inc])).mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText("INC0074444")).toBeInTheDocument());
    expect(screen.queryByText(/\d+ \w+ ago$/)).not.toBeInTheDocument();
  });

  // ── Priority normalization — bare text ──────────────────────────────────────

  it("translates bare priority text 'bajo' to 'Low'", async () => {
    const inc = { ...BASE_INC, incidentNumber: "INC0081111", priority: "bajo", workNotes: "—" };
    fetchMock.mockReturnValueOnce(okResponse([inc])).mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText("Low")).toBeInTheDocument());
    expect(screen.queryByText("bajo")).not.toBeInTheDocument();
  });

  // ── Columns menu ────────────────────────────────────────────────────────────

  it("opens the Columns menu when the Columns button is clicked", async () => {
    renderWithAutoFetch(fetchMock);
    render(<OperationsView />);
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "Columns" }));
    expect(screen.getByText("Incident Number")).toBeInTheDocument();
    expect(screen.getByText("Priority")).toBeInTheDocument();
  });

  it("toggles a column off when its entry in the Columns menu is clicked", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([BASE_INC]))
      .mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText("INC0012345")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Columns" }));
    const majorIncidentBtn = screen.getByRole("button", { name: "Major Incident" });
    fireEvent.click(majorIncidentBtn);
    expect(screen.queryByText("Yes")).not.toBeInTheDocument();
  });

  // ── Density menu ────────────────────────────────────────────────────────────

  it("opens the Density menu when the Density button is clicked", async () => {
    renderWithAutoFetch(fetchMock);
    render(<OperationsView />);
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "Density" }));
    expect(screen.getByText("compact")).toBeInTheDocument();
    expect(screen.getByText("standard")).toBeInTheDocument();
    expect(screen.getByText("comfortable")).toBeInTheDocument();
  });

  it("selects compact density when compact option is clicked", async () => {
    renderWithAutoFetch(fetchMock);
    render(<OperationsView />);
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "Density" }));
    fireEvent.click(screen.getByText("compact"));
    fireEvent.click(screen.getByRole("button", { name: "Density" }));
    expect(screen.queryByText("comfortable")).not.toBeInTheDocument();
  });

  // ── Refresh button ───────────────────────────────────────────────────────────

  it("clicking the Refresh button re-fetches both tabs", async () => {
    // mount: 2 calls; Refresh: 2 more = 4 total
    fetchMock.mockReturnValue(okResponse([BASE_INC]));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText("INC0012345")).toBeInTheDocument());
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    });
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("clicking the Refresh button on Change Requests tab re-fetches both", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([]))
      .mockReturnValueOnce(crResponse([BASE_CR]))
      .mockReturnValueOnce(okResponse([]))
      .mockReturnValueOnce(crResponse([BASE_CR]));
    render(<OperationsView />);
    fireEvent.click(screen.getByRole("button", { name: /^Change Requests/i }));
    await waitFor(() => expect(screen.getByText("CRQ001234")).toBeInTheDocument());
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    });
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  // ── Retry from error state ───────────────────────────────────────────────────

  it("retries the incidents fetch when 'Try Again' is clicked in the error state", async () => {
    fetchMock
      .mockReturnValueOnce(errResponse())         // mount incidents
      .mockReturnValueOnce(okResponse({ crqs: [] })) // mount CRs
      .mockReturnValueOnce(okResponse([BASE_INC]))  // retry incidents
      .mockReturnValueOnce(okResponse({ crqs: [] })); // retry CRs
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText("Try Again")).toBeInTheDocument());
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Try Again" }));
    });
    await waitFor(() => expect(screen.getByText("INC0012345")).toBeInTheDocument());
  });

  // ── Pagination ───────────────────────────────────────────────────────────────

  it("shows pagination footer after fetching incidents", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([BASE_INC]))
      .mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText("Rows per page:")).toBeInTheDocument());
  });

  it("shows 'No incidents match your filters' when active filters exclude all rows", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([BASE_INC]))
      .mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText("INC0012345")).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText(/search all columns/i), {
      target: { value: "ZZZNOMATCH999" },
    });
    expect(screen.getByText("No incidents match your filters")).toBeInTheDocument();
  });

  it("shows 'No change requests match your filters' when active CR filters exclude all rows", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([]))
      .mockReturnValueOnce(crResponse([BASE_CR]));
    render(<OperationsView />);
    fireEvent.click(screen.getByRole("button", { name: /^Change Requests/i }));
    await waitFor(() => expect(screen.getByText("CRQ001234")).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText(/search all columns/i), {
      target: { value: "ZZZNOMATCH999" },
    });
    expect(screen.getByText("No change requests match your filters")).toBeInTheDocument();
  });

  // ── Export ───────────────────────────────────────────────────────────────────

  it("clicking Export incidents does not throw and triggers a download", async () => {
    const createObjectURL = jest.fn().mockReturnValue("blob:mock");
    global.URL.createObjectURL = createObjectURL;
    global.URL.revokeObjectURL = jest.fn();
    fetchMock
      .mockReturnValueOnce(okResponse([BASE_INC]))
      .mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText("INC0012345")).toBeInTheDocument());
    expect(() => fireEvent.click(screen.getByRole("button", { name: "Export" }))).not.toThrow();
    expect(createObjectURL).toHaveBeenCalled();
  });

  it("clicking Export change requests does not throw and triggers a download", async () => {
    const createObjectURL = jest.fn().mockReturnValue("blob:mock");
    global.URL.createObjectURL = createObjectURL;
    global.URL.revokeObjectURL = jest.fn();
    fetchMock
      .mockReturnValueOnce(okResponse([]))
      .mockReturnValueOnce(crResponse([BASE_CR]));
    render(<OperationsView />);
    fireEvent.click(screen.getByRole("button", { name: /^Change Requests/i }));
    await waitFor(() => expect(screen.getByText("CRQ001234")).toBeInTheDocument());
    expect(() => fireEvent.click(screen.getByRole("button", { name: "Export" }))).not.toThrow();
    expect(createObjectURL).toHaveBeenCalled();
  });

  // ── CR inline search ────────────────────────────────────────────────────────

  it("shows the inline search input on the Change Requests tab", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([]))
      .mockReturnValueOnce(crResponse([BASE_CR]));
    render(<OperationsView />);
    fireEvent.click(screen.getByRole("button", { name: /^Change Requests/i }));
    await waitFor(() => expect(screen.getByText("CRQ001234")).toBeInTheDocument());
    expect(screen.getByPlaceholderText(/search all columns/i)).toBeInTheDocument();
  });

  it("filters change requests by search term via the inline search input", async () => {
    const cr2 = { ...BASE_CR, crqNumber: "CRQ009999", shortDescription: "Rollback deployment" };
    fetchMock
      .mockReturnValueOnce(okResponse([]))
      .mockReturnValueOnce(crResponse([BASE_CR, cr2]));
    render(<OperationsView />);
    fireEvent.click(screen.getByRole("button", { name: /^Change Requests/i }));
    await waitFor(() => expect(screen.getByText("CRQ001234")).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText(/search all columns/i), {
      target: { value: "CRQ009999" },
    });
    expect(screen.getByText("CRQ009999")).toBeInTheDocument();
    expect(screen.queryByText("CRQ001234")).not.toBeInTheDocument();
  });

  // ── Full Description modal for Change Requests ───────────────────────────────

  it("opens the Full Description modal when the info icon on a CR is clicked", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([]))
      .mockReturnValueOnce(crResponse([BASE_CR]));
    render(<OperationsView />);
    fireEvent.click(screen.getByRole("button", { name: /^Change Requests/i }));
    await waitFor(() => expect(screen.getByTitle("View full description")).toBeInTheDocument());
    fireEvent.click(screen.getByTitle("View full description"));
    expect(screen.getByText("Full Description")).toBeInTheDocument();
    expect(screen.getAllByText("Deploy new microservice").length).toBeGreaterThanOrEqual(1);
  });

  it("closes the Description modal when the backdrop is clicked", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([]))
      .mockReturnValueOnce(crResponse([BASE_CR]));
    render(<OperationsView />);
    fireEvent.click(screen.getByRole("button", { name: /^Change Requests/i }));
    await waitFor(() => expect(screen.getByTitle("View full description")).toBeInTheDocument());
    fireEvent.click(screen.getByTitle("View full description"));
    expect(screen.getByText("Full Description")).toBeInTheDocument();
    fireEvent.click(document.querySelector("div.fixed.inset-0") as HTMLElement);
    expect(screen.queryByText("Full Description")).not.toBeInTheDocument();
  });

  it("closes the Full Summary modal when the X button is clicked", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([BASE_INC]))
      .mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByTitle("View full summary")).toBeInTheDocument());
    fireEvent.click(screen.getByTitle("View full summary"));
    expect(screen.getByText("Full Summary")).toBeInTheDocument();
    fireEvent.click(document.querySelector("div.fixed.inset-0 button") as HTMLElement);
    expect(screen.queryByText("Full Summary")).not.toBeInTheDocument();
  });

  // ── Hours input ─────────────────────────────────────────────────────────────

  it("updates the hours value when the number input changes", async () => {
    renderWithAutoFetch(fetchMock);
    render(<OperationsView />);
    await act(async () => {});
    const numberInput = document.querySelector('input[type="number"]') as HTMLInputElement;
    fireEvent.change(numberInput, { target: { value: "48" } });
    expect(numberInput.value).toBe("48");
  });

  // ── CopyButton ───────────────────────────────────────────────────────────────

  it("clicking the copy button on an incident number calls clipboard.writeText", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([BASE_INC]))
      .mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText("INC0012345")).toBeInTheDocument());
    const copyBtn = screen.getByTitle("Copy");
    await act(async () => { fireEvent.click(copyBtn); });
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("INC0012345");
  });

  it("clears active incident filters by clearing the inline search input", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([BASE_INC]))
      .mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText("INC0012345")).toBeInTheDocument());
    const searchInput = screen.getByPlaceholderText(/search all columns/i);
    fireEvent.change(searchInput, { target: { value: "ZZZNOMATCH" } });
    expect(screen.getByText("No incidents match your filters")).toBeInTheDocument();
    fireEvent.change(searchInput, { target: { value: "" } });
    await waitFor(() => expect(screen.getByText("INC0012345")).toBeInTheDocument());
  });

  // ── str() with object values ────────────────────────────────────────────────

  it("renders an incident whose priority is an object with display_value", async () => {
    const inc = { ...BASE_INC, incidentNumber: "INC0090001", priority: { display_value: "1 - Critical" }, workNotes: "—" };
    fetchMock.mockReturnValueOnce(okResponse([inc])).mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText("INC0090001")).toBeInTheDocument());
    expect(screen.getByText("1 - Critical")).toBeInTheDocument();
  });

  it("renders medium priority badge for '3 - Medium'", async () => {
    const inc = { ...BASE_INC, incidentNumber: "INC0090002", priority: "3 - Medium", workNotes: "—" };
    fetchMock.mockReturnValueOnce(okResponse([inc])).mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText("3 - Medium")).toBeInTheDocument());
  });

  it("renders very-low priority badge for a 'p5' priority label", async () => {
    const inc = { ...BASE_INC, incidentNumber: "INC0090003", priority: "p5", workNotes: "—" };
    fetchMock.mockReturnValueOnce(okResponse([inc])).mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText("p5")).toBeInTheDocument());
    const badge = screen.getByText("p5");
    expect(badge.className).toContain("bg-gray-100");
  });

  it("renders critical-color badge when priority is ambiguous but category is security", async () => {
    const inc = { ...BASE_INC, incidentNumber: "INC0090004", priority: "unknown", category: "security incident", workNotes: "—" };
    fetchMock.mockReturnValueOnce(okResponse([inc])).mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText("INC0090004")).toBeInTheDocument());
    const badge = screen.getByText("unknown");
    expect(badge.className).toContain("bg-red-100");
  });

  it("silently handles clipboard.writeText rejection", async () => {
    fetchMock
      .mockReturnValueOnce(okResponse([BASE_INC]))
      .mockReturnValueOnce(okResponse({ crqs: [] }));
    render(<OperationsView />);
    await waitFor(() => expect(screen.getByText("INC0012345")).toBeInTheDocument());
    (navigator.clipboard.writeText as jest.Mock).mockRejectedValueOnce(new Error("not allowed"));
    await act(async () => { fireEvent.click(screen.getByTitle("Copy")); });
    expect(screen.getByText("INC0012345")).toBeInTheDocument();
  });

  // ── Click-outside closes dropdowns ──────────────────────────────────────────

  it("closes the Columns menu when clicking outside", async () => {
    renderWithAutoFetch(fetchMock);
    render(<OperationsView />);
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "Columns" }));
    expect(screen.getByText("Incident Number")).toBeInTheDocument();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByText("Incident Number")).not.toBeInTheDocument();
  });

  it("closes the Density menu when clicking outside", async () => {
    renderWithAutoFetch(fetchMock);
    render(<OperationsView />);
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "Density" }));
    expect(screen.getByText("compact")).toBeInTheDocument();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByText("compact")).not.toBeInTheDocument();
  });

  it("closes the CR Columns menu when clicking outside", async () => {
    renderWithAutoFetch(fetchMock);
    render(<OperationsView />);
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: /^Change Requests/i }));
    fireEvent.click(screen.getByRole("button", { name: "Columns" }));
    expect(screen.getByRole("button", { name: "CRQ Number" })).toBeInTheDocument();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("button", { name: "CRQ Number" })).not.toBeInTheDocument();
  });

  it("closes the CR Density menu when clicking outside", async () => {
    renderWithAutoFetch(fetchMock);
    render(<OperationsView />);
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: /^Change Requests/i }));
    fireEvent.click(screen.getByRole("button", { name: "Density" }));
    expect(screen.getByText("compact")).toBeInTheDocument();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByText("compact")).not.toBeInTheDocument();
  });
});
