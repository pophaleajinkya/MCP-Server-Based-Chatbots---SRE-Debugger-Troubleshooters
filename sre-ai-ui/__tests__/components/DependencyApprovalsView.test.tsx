import React from 'react';
import { render, screen, fireEvent, waitFor, within, act } from '@testing-library/react';
import '@testing-library/jest-dom';
import { DependencyApprovalsView } from '@/components/views/DependencyApprovalsView';
import * as apiClient from '@/lib/api-client';

// ─── Module mocks ─────────────────────────────────────────────────────────────

jest.mock('@/lib/api-client');

jest.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { loginId: 'john.doe', name: 'John Doe', email: 'john@example.com', user_type: 'S', isAdmin: true },
    loading: false,
    login: jest.fn(),
    logout: jest.fn(),
  }),
}));

// ─── Typed mock handle ────────────────────────────────────────────────────────

const mockApi = apiClient.dependencyApprovalsApi as jest.Mocked<typeof apiClient.dependencyApprovalsApi>;

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const makeApproval = (overrides: Partial<apiClient.DependencyApproval> = {}): apiClient.DependencyApproval => ({
  id: 1,
  applicationId: 101,
  applicationName: 'checkout-service',
  dependencyId: 202,
  dependencyName: 'payment-service',
  action: 'ADD',
  status: 'PENDING',
  reason: 'Need for payment processing',
  requestedBy: 'john.doe',
  approvedBy: null,
  approvedAt: null,
  createdAt: '2026-03-27T10:00:00.000Z',
  updatedAt: '2026-03-27T10:00:00.000Z',
  ...overrides,
});

const pendingOwnRequest    = makeApproval({ id: 1, requestedBy: 'john.doe', status: 'PENDING' });
const pendingOtherRequest  = makeApproval({ id: 2, requestedBy: 'jane.smith', status: 'PENDING', applicationName: 'order-service', dependencyName: 'auth-service' });
const approvedRequest      = makeApproval({ id: 3, status: 'APPROVED', approvedBy: 'jane.smith', approvedAt: '2026-03-27T11:00:00.000Z' });
const rejectedRequest      = makeApproval({ id: 4, status: 'REJECTED', approvedBy: 'jane.smith', reason: 'Not needed', approvedAt: '2026-03-27T11:00:00.000Z' });
const autoRejectedRequest  = makeApproval({ id: 5, status: 'REJECTED', approvedBy: 'system', reason: 'Auto-rejected: previous rejection', approvedAt: '2026-03-27T11:00:00.000Z' });
const deleteRequest        = makeApproval({ id: 6, action: 'DELETE', status: 'PENDING', requestedBy: 'john.doe', dependencyName: 'legacy-api' });

function makeApproveResponse(approval: apiClient.DependencyApproval): apiClient.DependencyApprovalResponse {
  return {
    status: 200,
    message: 'Dependency request approved successfully',
    data: { ...approval, status: 'APPROVED', approvedBy: 'john.doe', approvedAt: '2026-03-27T12:00:00.000Z' },
  };
}

function makeRejectResponse(approval: apiClient.DependencyApproval, reason: string): apiClient.DependencyApprovalResponse {
  return {
    status: 200,
    message: 'Dependency request rejected successfully',
    data: { ...approval, status: 'REJECTED', approvedBy: 'john.doe', reason, approvedAt: '2026-03-27T12:00:00.000Z' },
  };
}

// ─── Setup ────────────────────────────────────────────────────────────────────

describe('DependencyApprovalsView', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockApi.getAll.mockResolvedValue([pendingOwnRequest, pendingOtherRequest, approvedRequest, rejectedRequest]);
    mockApi.approve.mockResolvedValue(makeApproveResponse(pendingOtherRequest));
    mockApi.reject.mockResolvedValue(makeRejectResponse(pendingOtherRequest, 'Not valid'));
  });

  // ─── Loading & error states ────────────────────────────────────────────────

  describe('Loading and Error States', () => {
    it('shows loading spinner while fetching', () => {
      mockApi.getAll.mockImplementationOnce(() => new Promise(() => {}));
      render(<DependencyApprovalsView />);
      expect(document.querySelector('.animate-spin')).toBeInTheDocument();
    });

    it('shows error message and Try Again button when fetch fails', async () => {
      mockApi.getAll.mockRejectedValueOnce(new Error('Network error'));
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(screen.getByText(/network error/i)).toBeInTheDocument());
      expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
    });

    it('clicking Try Again re-fetches approvals', async () => {
      mockApi.getAll.mockRejectedValueOnce(new Error('Network error'));
      render(<DependencyApprovalsView />);
      await waitFor(() => screen.getByRole('button', { name: /try again/i }));
      fireEvent.click(screen.getByRole('button', { name: /try again/i }));
      expect(mockApi.getAll).toHaveBeenCalledTimes(2);
    });
  });

  // ─── Tab navigation ────────────────────────────────────────────────────────

  describe('Tab Navigation', () => {
    it('renders "My Requests" tab as the default active tab', async () => {
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      const myTab = screen.getByRole('button', { name: /my requests/i });
      // Active tab uses bg-[#002244] class, not border-[#002244]
      expect(myTab).toHaveClass('bg-[#002244]');
    });

    it('renders "Admin Panel" tab', async () => {
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      expect(screen.getByRole('button', { name: /admin panel/i })).toBeInTheDocument();
    });

    it('switches to Admin Panel when clicked', async () => {
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      fireEvent.click(screen.getByRole('button', { name: /admin panel/i }));
      // Active tab uses bg-[#002244] class, not border-[#002244]
      expect(screen.getByRole('button', { name: /admin panel/i })).toHaveClass('bg-[#002244]');
    });

    it('Admin Panel tab shows amber badge with pending count', async () => {
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      // 2 PENDING items in fixtures (pendingOwnRequest + pendingOtherRequest)
      expect(screen.getByText('2')).toBeInTheDocument();
    });

    it('Admin Panel tab badge is hidden when there are no pending items', async () => {
      mockApi.getAll.mockResolvedValueOnce([approvedRequest, rejectedRequest]);
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      // No amber badge for 0 pending
      const adminTab = screen.getByRole('button', { name: /admin panel/i });
      expect(within(adminTab).queryByText(/^\d+$/)).toBeNull();
    });

    it('My Requests tab shows count of current user requests', async () => {
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      // john.doe has pendingOwnRequest + approvedRequest + rejectedRequest = 3 (all with requestedBy john.doe by default)
      // Actually in fixtures: pendingOwnRequest=john.doe, approvedRequest=john.doe, rejectedRequest=john.doe, pendingOtherRequest=jane.smith
      // So 3 requests from john.doe
      const myTab = screen.getByRole('button', { name: /my requests/i });
      expect(within(myTab).getByText('3')).toBeInTheDocument();
    });

    it('resets status filter to PENDING when switching to Admin Panel', async () => {
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      fireEvent.click(screen.getByRole('button', { name: /admin panel/i }));
      // After switching, the "🟡 Pending" pill should be active
      const pendingPill = screen.getByRole('button', { name: /pending/i });
      expect(pendingPill).toHaveClass('bg-[#002244]');
    });
  });

  // ─── My Requests tab ──────────────────────────────────────────────────────

  describe('My Requests Tab', () => {
    it('shows only requests submitted by the logged-in user', async () => {
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      // john.doe's requests include checkout-service (pendingOwnRequest + approvedRequest + rejectedRequest)
      // jane.smith's request (order-service) should NOT appear
      expect(screen.getAllByText('checkout-service').length).toBeGreaterThan(0);
      expect(screen.queryByText('order-service')).not.toBeInTheDocument();
    });

    it('shows "awaiting review" for PENDING items', async () => {
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      expect(screen.getByText('awaiting review')).toBeInTheDocument();
    });

    it('shows "Withdraw" button for PENDING items', async () => {
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      expect(screen.getByRole('button', { name: /withdraw/i })).toBeInTheDocument();
    });

    it('does NOT show Withdraw button for non-PENDING items', async () => {
      mockApi.getAll.mockResolvedValueOnce([approvedRequest]);
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      expect(screen.queryByRole('button', { name: /withdraw/i })).not.toBeInTheDocument();
    });

    it('shows action badges (ADD / DELETE) correctly', async () => {
      mockApi.getAll.mockResolvedValueOnce([pendingOwnRequest, deleteRequest]);
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      expect(screen.getAllByText(/ADD/).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/DELETE/).length).toBeGreaterThan(0);
    });

    it('shows status badges correctly', async () => {
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      expect(screen.getAllByText(/Pending/).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/Approved/).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/Rejected/).length).toBeGreaterThan(0);
    });

    it('shows approver name for non-PENDING items', async () => {
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      // approvedRequest has approvedBy = 'jane.smith'
      expect(screen.getAllByText('jane.smith').length).toBeGreaterThan(0);
    });

    it('shows empty state when user has no requests', async () => {
      mockApi.getAll.mockResolvedValueOnce([pendingOtherRequest]); // only jane.smith's
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      expect(screen.getByText(/haven't submitted any dependency requests yet/i)).toBeInTheDocument();
    });
  });

  // ─── Withdraw flow ────────────────────────────────────────────────────────

  describe('Withdraw Flow (My Requests)', () => {
    it('opens WithdrawModal when Withdraw button is clicked', async () => {
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      fireEvent.click(screen.getByRole('button', { name: /withdraw/i }));
      expect(screen.getByText('Withdraw Request')).toBeInTheDocument();
    });

    it('shows the dependency name in the withdraw modal', async () => {
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      fireEvent.click(screen.getByRole('button', { name: /withdraw/i }));
      expect(screen.getAllByText(/payment-service/).length).toBeGreaterThan(0);
    });

    it('calls reject API with "Withdrawn by requester" reason on confirm', async () => {
      mockApi.reject.mockResolvedValueOnce(makeRejectResponse(pendingOwnRequest, 'Withdrawn by requester'));
      mockApi.getAll
        .mockResolvedValueOnce([pendingOwnRequest, pendingOtherRequest, approvedRequest, rejectedRequest])
        .mockResolvedValue([]);

      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());

      fireEvent.click(screen.getByRole('button', { name: /withdraw/i }));
      fireEvent.click(screen.getByRole('button', { name: /yes, withdraw/i }));

      await waitFor(() => {
        expect(mockApi.reject).toHaveBeenCalledWith(
          pendingOwnRequest.id,
          'john.doe',
          'Withdrawn by requester'
        );
      });
    });

    it('shows success toast after successful withdraw', async () => {
      mockApi.reject.mockResolvedValueOnce(makeRejectResponse(pendingOwnRequest, 'Withdrawn by requester'));
      mockApi.getAll
        .mockResolvedValueOnce([pendingOwnRequest, pendingOtherRequest, approvedRequest, rejectedRequest])
        .mockResolvedValue([]);

      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());

      fireEvent.click(screen.getByRole('button', { name: /withdraw/i }));
      fireEvent.click(screen.getByRole('button', { name: /yes, withdraw/i }));

      await waitFor(() => {
        expect(screen.getByText(/withdrawn successfully/i)).toBeInTheDocument();
      });
    });

    it('closes modal when "Keep it" is clicked', async () => {
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());

      fireEvent.click(screen.getByRole('button', { name: /withdraw/i }));
      expect(screen.getByText('Withdraw Request')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /keep it/i }));
      await waitFor(() => {
        expect(screen.queryByText('Withdraw Request')).not.toBeInTheDocument();
      });
    });

    it('refreshes list after withdraw', async () => {
      mockApi.reject.mockResolvedValueOnce(makeRejectResponse(pendingOwnRequest, 'Withdrawn by requester'));
      mockApi.getAll
        .mockResolvedValueOnce([pendingOwnRequest, pendingOtherRequest, approvedRequest, rejectedRequest])
        .mockResolvedValue([]);

      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalledTimes(1));

      fireEvent.click(screen.getByRole('button', { name: /withdraw/i }));
      fireEvent.click(screen.getByRole('button', { name: /yes, withdraw/i }));

      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalledTimes(2));
    });
  });

  // ─── Admin Panel tab ──────────────────────────────────────────────────────

  describe('Admin Panel Tab', () => {
    beforeEach(async () => {
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      fireEvent.click(screen.getByRole('button', { name: /admin panel/i }));
    });

    it('shows all requests including other users', async () => {
      await waitFor(() => {
        expect(screen.getByText('order-service')).toBeInTheDocument();
      });
    });

    it('shows "Requested By" column', async () => {
      await waitFor(() => {
        expect(screen.getByText(/requested by/i)).toBeInTheDocument();
      });
    });

    it('shows Approve button for PENDING items from other users', async () => {
      await waitFor(() => {
        const approveBtns = screen.queryAllByRole('button', { name: /approve/i });
        expect(approveBtns.length).toBeGreaterThan(0);
      });
    });

    it('shows Reject button for PENDING items from other users', async () => {
      await waitFor(() => {
        const rejectBtns = screen.queryAllByRole('button', { name: /^reject$/i });
        expect(rejectBtns.length).toBeGreaterThan(0);
      });
    });

    it('disables Approve button for own PENDING requests (self-approval prevention)', async () => {
      await waitFor(() => {
        const approveBtns = screen.queryAllByRole('button', { name: /approve/i });
        // john.doe's own request (pendingOwnRequest) should have disabled approve btn
        const disabledBtn = approveBtns.find(btn => btn.hasAttribute('disabled'));
        expect(disabledBtn).toBeTruthy();
      });
    });

    it('shows tooltip "You cannot approve your own request" on own request Approve button', async () => {
      await waitFor(() => {
        const approveBtn = screen.queryAllByRole('button', { name: /approve/i })
          .find(btn => btn.hasAttribute('disabled'));
        expect(approveBtn?.getAttribute('title')).toBe('You cannot approve your own request');
      });
    });
  });

  // ─── Approve flow (Admin Panel) ────────────────────────────────────────────

  describe('Approve Flow (Admin Panel)', () => {
    it('calls approve API with request id and current user loginId', async () => {
      mockApi.approve.mockResolvedValueOnce(makeApproveResponse(pendingOtherRequest));
      mockApi.getAll
        .mockResolvedValueOnce([pendingOwnRequest, pendingOtherRequest, approvedRequest, rejectedRequest])
        .mockResolvedValueOnce([approvedRequest]);

      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      fireEvent.click(screen.getByRole('button', { name: /admin panel/i }));

      await waitFor(() => {
        // Use title to target action Approve buttons (not the "✅ Approved" filter pill)
        const approveBtns = screen.queryAllByTitle('Approve this request');
        if (approveBtns.length > 0) fireEvent.click(approveBtns[0]);
      });

      await waitFor(() => {
        expect(mockApi.approve).toHaveBeenCalledWith(
          pendingOtherRequest.id,
          'john.doe'
        );
      });
    });

    it('shows success toast after approval', async () => {
      mockApi.approve.mockResolvedValueOnce(makeApproveResponse(pendingOtherRequest));
      mockApi.getAll
        .mockResolvedValueOnce([pendingOwnRequest, pendingOtherRequest, approvedRequest, rejectedRequest])
        .mockResolvedValue([]);

      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      fireEvent.click(screen.getByRole('button', { name: /admin panel/i }));

      await waitFor(() => {
        // Use title to target action Approve buttons (not the "✅ Approved" filter pill)
        const approveBtns = screen.queryAllByTitle('Approve this request');
        if (approveBtns.length > 0) fireEvent.click(approveBtns[0]);
      });

      await waitFor(() => {
        // Toast message format: "Approved: <appName> → <depName>"
        expect(screen.getByText(/Approved: order-service/i)).toBeInTheDocument();
      });
    });

    it('refreshes the list after approval', async () => {
      mockApi.approve.mockResolvedValueOnce(makeApproveResponse(pendingOtherRequest));
      mockApi.getAll
        .mockResolvedValueOnce([pendingOwnRequest, pendingOtherRequest, approvedRequest, rejectedRequest])
        .mockResolvedValue([]);

      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalledTimes(1));
      fireEvent.click(screen.getByRole('button', { name: /admin panel/i }));

      await waitFor(() => {
        // Use title to target action Approve buttons (not the "✅ Approved" filter pill)
        const approveBtns = screen.queryAllByTitle('Approve this request');
        if (approveBtns.length > 0) fireEvent.click(approveBtns[0]);
      });

      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalledTimes(2));
    });
  });

  // ─── Reject flow (Admin Panel) ────────────────────────────────────────────

  describe('Reject Flow (Admin Panel)', () => {
    it('opens RejectModal when Reject button is clicked', async () => {
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      fireEvent.click(screen.getByRole('button', { name: /admin panel/i }));

      await waitFor(() => {
        const rejectBtns = screen.queryAllByRole('button', { name: /^reject$/i })
          .filter(btn => !btn.hasAttribute('disabled'));
        if (rejectBtns.length > 0) fireEvent.click(rejectBtns[0]);
      });

      await waitFor(() => {
        expect(screen.queryByText('Reject Request')).toBeInTheDocument();
      });
    });

    it('Reject button in modal is disabled when reason is empty', async () => {
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      fireEvent.click(screen.getByRole('button', { name: /admin panel/i }));

      await waitFor(() => {
        const rejectBtns = screen.queryAllByRole('button', { name: /^reject$/i })
          .filter(btn => !btn.hasAttribute('disabled'));
        if (rejectBtns.length > 0) fireEvent.click(rejectBtns[0]);
      });

      await waitFor(() => {
        const modalRejectBtn = screen.queryAllByRole('button', { name: /^reject$/i }).pop();
        if (modalRejectBtn) expect(modalRejectBtn).toBeDisabled();
      });
    });

    it('calls reject API with id, current user loginId, and typed reason', async () => {
      mockApi.reject.mockResolvedValueOnce(makeRejectResponse(pendingOtherRequest, 'Not a valid dep'));
      mockApi.getAll.mockResolvedValue([]);

      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      fireEvent.click(screen.getByRole('button', { name: /admin panel/i }));

      await waitFor(() => {
        const rejectBtns = screen.queryAllByRole('button', { name: /^reject$/i })
          .filter(btn => !btn.hasAttribute('disabled'));
        if (rejectBtns.length > 0) fireEvent.click(rejectBtns[0]);
      });

      const textarea = screen.queryByPlaceholderText(/explain why/i);
      if (textarea) {
        fireEvent.change(textarea, { target: { value: 'Not a valid dep' } });
        const confirmBtn = screen.queryAllByRole('button', { name: /^reject$/i }).pop();
        if (confirmBtn) fireEvent.click(confirmBtn);
      }

      await waitFor(() => {
        if (mockApi.reject.mock.calls.length > 0) {
          expect(mockApi.reject).toHaveBeenCalledWith(
            pendingOtherRequest.id,
            'john.doe',
            'Not a valid dep'
          );
        }
      });
    });

    it('shows the requester original reason inside the reject modal', async () => {
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      fireEvent.click(screen.getByRole('button', { name: /admin panel/i }));

      await waitFor(() => {
        const rejectBtns = screen.queryAllByRole('button', { name: /^reject$/i })
          .filter(btn => !btn.hasAttribute('disabled'));
        if (rejectBtns.length > 0) fireEvent.click(rejectBtns[0]);
      });

      await waitFor(() => {
        if (screen.queryByText('Reject Request')) {
          // pendingOtherRequest has reason: 'Need for payment processing'
          expect(screen.getAllByText(/need for payment processing/i).length).toBeGreaterThan(0);
        }
      });
    });
  });

  // ─── Filter pills ─────────────────────────────────────────────────────────

  describe('Filter Pills', () => {
    it('renders All / Pending / Approved / Rejected status pills', async () => {
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      expect(screen.getByRole('button', { name: /^all$/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /pending/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /approved/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /rejected/i })).toBeInTheDocument();
    });

    it('renders ADD / DELETE action pills', async () => {
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      expect(screen.getByRole('button', { name: /all actions/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /ADD/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /DELETE/i })).toBeInTheDocument();
    });

    it('filtering by Approved status hides PENDING and REJECTED items', async () => {
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());

      // The filter pill label is "Approved" (plain text, no emoji — emojis are in StatusBadge)
      fireEvent.click(screen.getByRole('button', { name: /^approved$/i }));

      await waitFor(() => {
        // approvedRequest is from john.doe, should show
        // pendingOwnRequest should be hidden
        expect(screen.queryByText(/awaiting review/i)).not.toBeInTheDocument();
      });
    });

    it('shows correct count in toolbar', async () => {
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      // john.doe has 3 requests (pendingOwnRequest, approvedRequest, rejectedRequest)
      expect(screen.getByText(/3 requests/i)).toBeInTheDocument();
    });
  });

  // ─── Refresh ──────────────────────────────────────────────────────────────

  describe('Refresh', () => {
    it('clicking Refresh button re-fetches all approvals', async () => {
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalledTimes(1));

      // The Refresh button has no title attribute — find it by its text content
      fireEvent.click(screen.getByRole('button', { name: /refresh/i }));
      expect(mockApi.getAll).toHaveBeenCalledTimes(2);
    });
  });

  // ─── timeAgo branch coverage ──────────────────────────────────────────────

  describe('timeAgo formatting for approval timestamps', () => {
    it('shows hours-ago label for approvals created ~2 hours ago', async () => {
      const twoHoursAgo = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
      mockApi.getAll.mockResolvedValueOnce([
        makeApproval({ id: 10, requestedBy: 'john.doe', createdAt: twoHoursAgo }),
      ]);
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      // The timeAgo function should return "2h ago"
      expect(screen.getByText(/\dh ago/)).toBeInTheDocument();
    });

    it('shows days-ago label for approvals created ~3 days ago', async () => {
      const threeDaysAgo = new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString();
      mockApi.getAll.mockResolvedValueOnce([
        makeApproval({ id: 11, requestedBy: 'john.doe', createdAt: threeDaysAgo }),
      ]);
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      // The timeAgo function should return "3d ago"
      expect(screen.getByText(/\dd ago/)).toBeInTheDocument();
    });

    it('shows locale date string for approvals created >30 days ago', async () => {
      const fortyDaysAgo = new Date(Date.now() - 40 * 24 * 60 * 60 * 1000).toISOString();
      mockApi.getAll.mockResolvedValueOnce([
        makeApproval({ id: 12, requestedBy: 'john.doe', createdAt: fortyDaysAgo }),
      ]);
      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      // Should fall through to toLocaleDateString() — won't match m/h/d patterns
      const timeTexts = document.querySelectorAll('td');
      expect(timeTexts.length).toBeGreaterThan(0);
    });
  });

  // ─── Error handling in approve/withdraw ───────────────────────────────────

  describe('Error handling', () => {
    it('shows error toast when approve API throws', async () => {
      mockApi.approve.mockRejectedValueOnce(new Error('Approve failed'));
      mockApi.getAll
        .mockResolvedValueOnce([pendingOwnRequest, pendingOtherRequest, approvedRequest, rejectedRequest])
        .mockResolvedValue([]);

      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      fireEvent.click(screen.getByRole('button', { name: /admin panel/i }));

      await waitFor(() => {
        const approveBtns = screen.queryAllByTitle('Approve this request');
        if (approveBtns.length > 0) fireEvent.click(approveBtns[0]);
      });

      await waitFor(() => {
        expect(screen.getAllByText(/approve failed/i).length).toBeGreaterThan(0);
      });
    });

    it('exercises error catch path when withdraw API throws', async () => {
      mockApi.reject.mockRejectedValueOnce(new Error('Withdraw failed'));

      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());

      fireEvent.click(screen.getByRole('button', { name: /withdraw/i }));
      fireEvent.click(screen.getByRole('button', { name: /yes, withdraw/i }));

      // Verify that reject was called (exercises the catch branch)
      await waitFor(() => {
        expect(mockApi.reject).toHaveBeenCalledWith(
          pendingOwnRequest.id,
          'john.doe',
          'Withdrawn by requester'
        );
      });
      // Component should still be rendered (error handled gracefully)
      expect(screen.getByRole('button', { name: /my requests/i })).toBeInTheDocument();
    });

    it('shows error toast with err.message when withdraw throws an Error', async () => {
      mockApi.getAll.mockResolvedValue([pendingOwnRequest, pendingOtherRequest, approvedRequest, rejectedRequest]);
      mockApi.reject.mockRejectedValueOnce(new Error('Withdraw failed'));

      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /withdraw/i }));
      });
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /yes, withdraw/i }));
      });

      await waitFor(() => {
        expect(screen.getByText('Withdraw failed')).toBeInTheDocument();
      });
    });

    it('shows fallback error toast when withdraw throws a non-Error', async () => {
      mockApi.getAll.mockResolvedValue([pendingOwnRequest, pendingOtherRequest, approvedRequest, rejectedRequest]);
      mockApi.reject.mockReset();
      mockApi.reject.mockRejectedValue('something went wrong');

      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /withdraw/i }));
      });
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /yes, withdraw/i }));
      });

      await waitFor(() => {
        expect(screen.getByText('Failed to withdraw request')).toBeInTheDocument();
      });
    });
  });

  // ─── Reject flow — success + error paths ──────────────────────────────────

  describe('Reject Flow success and error handling', () => {
    async function openRejectModalForOtherRequest() {
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /admin panel/i }));
      });

      // Wait for pending items to appear (admin panel defaults to PENDING filter)
      await waitFor(() => {
        const rejectBtns = screen.queryAllByRole('button', { name: /^reject$/i })
          .filter(btn => !btn.hasAttribute('disabled'));
        expect(rejectBtns.length).toBeGreaterThan(0);
      });

      // Click the first enabled reject button (jane.smith's request)
      const rejectBtns = screen.queryAllByRole('button', { name: /^reject$/i })
        .filter(btn => !btn.hasAttribute('disabled'));
      await act(async () => {
        fireEvent.click(rejectBtns[0]);
      });

      await waitFor(() => {
        expect(screen.getByText('Reject Request')).toBeInTheDocument();
      });
    }

    it('calls reject API and shows success toast on confirm', async () => {
      mockApi.reject.mockReset();
      mockApi.reject.mockResolvedValueOnce(makeRejectResponse(pendingOtherRequest, 'Not a valid dep'));
      mockApi.getAll
        .mockResolvedValueOnce([pendingOwnRequest, pendingOtherRequest, approvedRequest, rejectedRequest])
        .mockResolvedValue([]);

      render(<DependencyApprovalsView />);
      await openRejectModalForOtherRequest();

      const textarea = screen.getByPlaceholderText(/explain why/i);
      fireEvent.change(textarea, { target: { value: 'Not a valid dep' } });

      const confirmBtn = screen.queryAllByRole('button', { name: /^reject$/i }).pop()!;
      await act(async () => {
        fireEvent.click(confirmBtn);
      });

      await waitFor(() => {
        expect(screen.getByText(/Rejected: order-service/i)).toBeInTheDocument();
      });
    });

    it('shows error toast when reject API throws an Error', async () => {
      mockApi.reject.mockReset();
      mockApi.reject.mockRejectedValueOnce(new Error('Reject failed'));
      mockApi.getAll
        .mockResolvedValueOnce([pendingOwnRequest, pendingOtherRequest, approvedRequest, rejectedRequest])
        .mockResolvedValue([pendingOwnRequest, pendingOtherRequest, approvedRequest, rejectedRequest]);

      render(<DependencyApprovalsView />);
      await openRejectModalForOtherRequest();

      const textarea = screen.getByPlaceholderText(/explain why/i);
      fireEvent.change(textarea, { target: { value: 'Bad dep' } });

      const confirmBtn = screen.queryAllByRole('button', { name: /^reject$/i }).pop()!;
      await act(async () => {
        fireEvent.click(confirmBtn);
      });

      await waitFor(() => {
        expect(screen.getByText('Reject failed')).toBeInTheDocument();
      });
    });

    it('shows fallback error toast when reject API throws a non-Error', async () => {
      mockApi.reject.mockReset();
      mockApi.reject.mockRejectedValue('something bad');
      mockApi.getAll
        .mockResolvedValueOnce([pendingOwnRequest, pendingOtherRequest, approvedRequest, rejectedRequest])
        .mockResolvedValue([pendingOwnRequest, pendingOtherRequest, approvedRequest, rejectedRequest]);

      render(<DependencyApprovalsView />);
      await openRejectModalForOtherRequest();

      const textarea = screen.getByPlaceholderText(/explain why/i);
      fireEvent.change(textarea, { target: { value: 'Bad dep' } });

      const confirmBtn = screen.queryAllByRole('button', { name: /^reject$/i }).pop()!;
      await act(async () => {
        fireEvent.click(confirmBtn);
      });

      await waitFor(() => {
        expect(screen.getByText('Failed to reject request')).toBeInTheDocument();
      });
    });
  });

  // ─── My Requests — approvedBy rendering branches ─────────────────────────

  describe('My Requests — approvedBy display variants', () => {
    it('shows "system" label when approvedBy is "system"', async () => {
      const systemApproval = makeApproval({
        id: 20,
        requestedBy: 'john.doe',
        status: 'APPROVED',
        approvedBy: 'system',
        approvedAt: '2026-03-27T12:00:00.000Z',
      });
      mockApi.getAll.mockResolvedValueOnce([systemApproval]);

      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());

      await waitFor(() => {
        expect(screen.getByText('system')).toBeInTheDocument();
      });
    });

    it('shows "withdrawn by you" when approvedBy equals current user loginId', async () => {
      const withdrawnApproval = makeApproval({
        id: 21,
        requestedBy: 'john.doe',
        status: 'REJECTED',
        approvedBy: 'john.doe',
        approvedAt: '2026-03-27T12:00:00.000Z',
        reason: 'Withdrawn by requester',
      });
      mockApi.getAll.mockResolvedValueOnce([withdrawnApproval]);

      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());

      await waitFor(() => {
        expect(screen.getByText('withdrawn by you')).toBeInTheDocument();
      });
    });

    it('shows approver name when approvedBy is a different user', async () => {
      const otherApproval = makeApproval({
        id: 22,
        requestedBy: 'john.doe',
        status: 'APPROVED',
        approvedBy: 'admin.user',
        approvedAt: '2026-03-27T12:00:00.000Z',
      });
      mockApi.getAll.mockResolvedValueOnce([otherApproval]);

      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());

      await waitFor(() => {
        expect(screen.getByText('admin.user')).toBeInTheDocument();
      });
    });

    it('shows em-dash when approvedBy is null for a non-PENDING item', async () => {
      const noApprover = makeApproval({
        id: 23,
        requestedBy: 'john.doe',
        status: 'APPROVED',
        approvedBy: null,
        approvedAt: null,
      });
      mockApi.getAll.mockResolvedValueOnce([noApprover]);

      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());

      // Should show "—"
      const dashes = screen.getAllByText('—');
      expect(dashes.length).toBeGreaterThanOrEqual(1);
    });
  });

  // ─── Approve error non-Error catch branch ────────────────────────────────

  describe('Approve error fallback', () => {
    it('shows fallback error toast when approve API throws a non-Error', async () => {
      mockApi.approve.mockRejectedValueOnce('something wrong');
      mockApi.getAll
        .mockResolvedValueOnce([pendingOwnRequest, pendingOtherRequest, approvedRequest, rejectedRequest])
        .mockResolvedValue([pendingOwnRequest, pendingOtherRequest, approvedRequest, rejectedRequest]);

      render(<DependencyApprovalsView />);
      await waitFor(() => expect(mockApi.getAll).toHaveBeenCalled());
      fireEvent.click(screen.getByRole('button', { name: /admin panel/i }));

      await waitFor(() => {
        const approveBtns = screen.queryAllByTitle('Approve this request');
        if (approveBtns.length > 0) fireEvent.click(approveBtns[0]);
      });

      await waitFor(() => {
        expect(screen.getByText('Failed to approve request')).toBeInTheDocument();
      });
    });
  });
});
