"use client";

import { useState, useEffect } from "react";
import { Pause, Play, Zap, Square, CheckCircle, AlertTriangle } from "lucide-react";
import { 
  scheduleAlertRetry, 
  getScheduledAlerts, 
  pauseAlertRetry, 
  resumeAlertRetry, 
  stopAlertRetry,
  runNowAlertRetry
} from "@/lib/works-client";

// Browser-side time anchor forwarded to openclaw/super-agent so LLM tools
// can resolve relative time expressions in the user's timezone regardless of
// which pod (or server TZ) runs the tick.
function browserTimeExtras(): { timezone: string; currentEpochMs: number } {
  return {
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    currentEpochMs: Date.now(),
  };
}

export function AlertRetryScheduler({ initialAlertId, conversationId }: { initialAlertId: string | null, conversationId: string }) {
  const [alertId, setAlertId] = useState(initialAlertId || "");
  const [delayMinutes, setDelayMinutes] = useState(5);
  const [maxInvocations, setMaxInvocations] = useState(3);
  const [customPrompt, setCustomPrompt] = useState("");
  const [currentInvocation, setCurrentInvocation] = useState(1);
  
  const [status, setStatus] = useState<"idle" | "loading" | "scheduled" | "paused" | "error" | "resolved" | "max_retries_reached">("idle");
  const [errorMsg, setErrorMsg] = useState("");
  const [runAtEpoch, setRunAtEpoch] = useState<number | null>(null);
  const [remainingSeconds, setRemainingSeconds] = useState<number | null>(null);

  const [isActionLoading, setIsActionLoading] = useState(false);
  const [isFetchingInitial, setIsFetchingInitial] = useState(true);

  // Check if there is already a scheduled retry for this conversation/alert
  useEffect(() => {
    if (!conversationId) return;
    
    let isMounted = true;
    
    async function fetchSchedules() {
      try {
        const { data } = await getScheduledAlerts(conversationId);
        if (isMounted && data) {
          // If we have an initialAlertId and it's tracked, or if there's only one tracked alert overall
          const trackedAlert = initialAlertId && data[initialAlertId] 
            ? data[initialAlertId] 
            : Object.values(data)[0] as any;

          if (trackedAlert) {
            setAlertId(initialAlertId || Object.keys(data)[0]);
            setDelayMinutes(trackedAlert.delay_minutes);
            setMaxInvocations(trackedAlert.max_invocations);
            setCurrentInvocation(trackedAlert.current_invocation || 1);
            setCustomPrompt(trackedAlert.custom_prompt || "");
            
            setStatus(trackedAlert.status as any);
            
            if (trackedAlert.status === "scheduled" && trackedAlert.run_at_epoch) {
              setRunAtEpoch(trackedAlert.run_at_epoch);
            } else {
              setRunAtEpoch(null);
              setRemainingSeconds(null);
            }
          } else {
            // Edge Case: If the backend has no schedules, reset to idle.
            setStatus((prev) => {
              if (prev === "loading" || prev === "error") return prev;
              return "idle";
            });
            setRunAtEpoch(null);
            setRemainingSeconds(null);
          }
        }
      } catch (err) {
        console.error("Failed to fetch schedules:", err);
      } finally {
        if (isMounted) setIsFetchingInitial(false);
      }
    }
    
    // Initial fetch
    fetchSchedules();
    
    // Polling logic: constantly check backend while scheduled to keep in sync
    // after "Run Now" or normal background executions.
    const pollInterval = setInterval(() => {
      fetchSchedules();
    }, 10000); // Check every 10 seconds to avoid drift
    
    return () => { 
      isMounted = false; 
      clearInterval(pollInterval);
    };
  }, [conversationId, initialAlertId]);

  // Live countdown timer
  useEffect(() => {
    if (status !== "scheduled" || !runAtEpoch) return;

    const calculateRemaining = () => {
      const now = Date.now() / 1000;
      return Math.max(0, Math.floor(runAtEpoch - now));
    };

    setRemainingSeconds(calculateRemaining());

    const interval = setInterval(() => {
      setRemainingSeconds(calculateRemaining());
    }, 1000);

    return () => clearInterval(interval);
  }, [status, runAtEpoch]);

  async function handleSchedule() {
    if (!alertId.trim()) {
      setErrorMsg("Alert ID is required");
      setStatus("error");
      return;
    }
    
    setStatus("loading");
    try {
      const promptToUse = customPrompt.trim() ? customPrompt.trim() : null;
      const result = await scheduleAlertRetry(alertId.trim(), conversationId, delayMinutes, maxInvocations, promptToUse, browserTimeExtras());
      if (result.error) {
        throw new Error(result.error);
      }
      setStatus("scheduled");
      setRunAtEpoch(Date.now() / 1000 + delayMinutes * 60);
      setCurrentInvocation(1);
    } catch (err: any) {
      setErrorMsg(err.message);
      setStatus("error");
    }
  }

  async function handleAction(action: "pause" | "resume" | "stop" | "run_now") {
    setIsActionLoading(true);
    setErrorMsg("");
    try {
      let result;
      if (action === "pause") {
        result = await pauseAlertRetry(alertId.trim(), conversationId);
      } else if (action === "resume") {
        result = await resumeAlertRetry(alertId.trim(), conversationId, browserTimeExtras());
      } else if (action === "stop") {
        result = await stopAlertRetry(alertId.trim(), conversationId);
      } else if (action === "run_now") {
        result = await runNowAlertRetry(alertId.trim(), conversationId, browserTimeExtras());
      }
      
      if (result && "error" in result && result.error) {
        throw new Error(result.error);
      }

      if (action === "pause") {
        setStatus("paused");
        setRunAtEpoch(null);
        setRemainingSeconds(null);
      } else if (action === "resume") {
        setStatus("scheduled");
        setRunAtEpoch(Date.now() / 1000 + delayMinutes * 60);
      } else if (action === "stop") {
        setStatus("idle");
        setRunAtEpoch(null);
        setRemainingSeconds(null);
        setAlertId(initialAlertId || "");
      } else if (action === "run_now") {
        setStatus("scheduled");
        setRunAtEpoch(Date.now() / 1000 + 3); // Running in 3 seconds!
        setRemainingSeconds(3);
      }
    } catch (err: any) {
      setErrorMsg(err.message);
      // We don't change status to error if action fails, just show error msg
    } finally {
      setIsActionLoading(false);
    }
  }

  const formatRemainingTime = (seconds: number) => {
    if (seconds <= 0) return "Running now...";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
  };

  if (isFetchingInitial) {
    return (
      <div className="mt-2 p-3 bg-gray-50 border border-gray-100 rounded-lg flex items-center gap-3 animate-pulse">
        <div className="w-4 h-4 bg-gray-200 rounded-full" />
        <div className="h-2.5 bg-gray-200 rounded w-1/3" />
      </div>
    );
  }

  if (status === "resolved" || status === "max_retries_reached") {
    const isSuccess = status === "resolved";
    return (
      <div className={`mt-2 p-3 border rounded-lg text-xs flex flex-col gap-2 ${
        isSuccess ? "bg-green-50 border-green-200 text-green-800" : "bg-red-50 border-red-200 text-red-800"
      }`}>
        <div className="flex items-center gap-2 font-medium">
          {isSuccess ? <CheckCircle className="w-4 h-4 text-green-600" /> : <AlertTriangle className="w-4 h-4 text-red-600" />}
          <span>
            {isSuccess 
              ? `Monitoring Complete: Alert ${alertId} was resolved.`
              : `Monitoring Ended: Alert ${alertId} reached max retries (${maxInvocations}).`}
          </span>
          <button 
            onClick={() => handleAction("stop")}
            disabled={isActionLoading}
            className="ml-auto px-2 py-1 bg-white border shadow-sm rounded text-gray-700 hover:bg-gray-50 transition-colors"
          >
            Dismiss
          </button>
        </div>
      </div>
    );
  }

  if (status === "scheduled" || status === "paused") {
    return (
      <div className={`mt-2 p-3 border rounded-lg text-xs flex flex-col gap-2 ${
        status === "scheduled" 
          ? "bg-green-50 border-green-200 text-green-800" 
          : "bg-yellow-50 border-yellow-200 text-yellow-800"
      }`}>
        <div className="flex items-start gap-2 font-medium">
          {status === "scheduled" ? (
            <span className="w-2 h-2 mt-1 rounded-full bg-green-500 animate-pulse flex-shrink-0" />
          ) : (
            <span className="w-2 h-2 mt-1 rounded-full bg-yellow-500 flex-shrink-0" />
          )}
          <div className="flex-1">
            <div>
              {status === "scheduled" ? "Monitoring" : "Paused monitoring for"} alert <strong>{alertId}</strong> every {delayMinutes}m.
            </div>
            <div className="text-gray-600 mt-0.5 opacity-80">
              Attempt {currentInvocation} of {maxInvocations}
            </div>
            {customPrompt && (
              <div className="mt-1 italic opacity-75 break-words">
                &quot;{customPrompt}&quot;
              </div>
            )}
          </div>
          {status === "scheduled" && remainingSeconds !== null && (
            <span className="font-semibold ml-auto text-green-700 whitespace-nowrap">
              Next: {formatRemainingTime(remainingSeconds)}
            </span>
          )}
        </div>
        
        {errorMsg && <div className="text-red-500 font-medium">{errorMsg}</div>}
        
        <div className="flex gap-2 mt-1 flex-wrap">
          {status === "scheduled" ? (
            <button 
              onClick={() => handleAction("pause")}
              disabled={isActionLoading || (remainingSeconds !== null && remainingSeconds <= 3)}
              className="flex items-center gap-1.5 px-3 py-1 bg-yellow-500 text-white rounded hover:bg-yellow-600 disabled:opacity-50 transition-colors"
            >
              <Pause className="w-3.5 h-3.5" /> Pause
            </button>
          ) : (
            <button 
              onClick={() => handleAction("resume")}
              disabled={isActionLoading}
              className="flex items-center gap-1.5 px-3 py-1 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 transition-colors"
            >
              <Play className="w-3.5 h-3.5" /> Resume
            </button>
          )}
          <button 
            onClick={() => handleAction("run_now")}
            disabled={isActionLoading || (remainingSeconds !== null && remainingSeconds <= 3)}
            className="flex items-center gap-1.5 px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 transition-colors"
            title="Execute the check immediately"
          >
            <Zap className="w-3.5 h-3.5" /> Check Now
          </button>
          <button 
            onClick={() => handleAction("stop")}
            disabled={isActionLoading}
            className="flex items-center gap-1.5 px-3 py-1 bg-red-500 text-white rounded hover:bg-red-600 disabled:opacity-50 transition-colors"
          >
            <Square className="w-3.5 h-3.5 fill-current" /> Stop
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="mt-2 p-3 bg-blue-50/50 border border-blue-100 rounded-lg text-xs flex flex-col gap-3">
      <div className="font-semibold text-blue-800">Schedule Follow-up Monitoring</div>
      
      <div className="flex flex-col gap-2">
        <div className="flex gap-4 items-center flex-wrap">
          <label className="flex items-center gap-2 text-gray-700">
            Alert ID:
            <input 
              type="text" 
              value={alertId} 
              onChange={(e) => setAlertId(e.target.value)}
              placeholder="e.g. INC1234567"
              className="w-28 p-1.5 border rounded bg-white text-gray-900"
              disabled={status === "loading"}
            />
          </label>

          <label className="flex items-center gap-2 text-gray-700">
            Interval (min):
            <input 
              type="number" min={5} max={30} value={delayMinutes} 
              onChange={(e) => setDelayMinutes(Number(e.target.value))}
              className="w-16 p-1.5 border rounded bg-white text-gray-900"
              disabled={status === "loading"}
            />
          </label>
          
          <label className="flex items-center gap-2 text-gray-700">
            Retries:
            <input 
              type="number" min={1} max={10} value={maxInvocations} 
              onChange={(e) => setMaxInvocations(Number(e.target.value))}
              className="w-16 p-1.5 border rounded bg-white text-gray-900"
              disabled={status === "loading"}
            />
          </label>
        </div>

        <label className="flex flex-col gap-1 text-gray-700 w-full mt-1">
          <span className="opacity-80">Custom Agent Instructions (Optional):</span>
          <textarea 
            value={customPrompt}
            onChange={(e) => setCustomPrompt(e.target.value)}
            placeholder="e.g. Focus strictly on whether the memory metric dropped below 80%..."
            className="w-full p-2 border rounded bg-white text-gray-900 resize-none min-h-[60px]"
            disabled={status === "loading"}
          />
        </label>
      </div>

      <div className="flex items-center mt-1">
        <button 
          onClick={handleSchedule}
          disabled={status === "loading" || !alertId.trim()}
          className="flex items-center gap-1.5 px-4 py-1.5 bg-[#0071CE] text-white rounded hover:bg-[#005baa] disabled:opacity-50 transition-colors font-medium"
        >
          {status === "loading" ? "Processing..." : <><Play className="w-3.5 h-3.5" /> Start Monitoring</>}
        </button>
        {status === "error" && <div className="text-red-500 ml-3 font-medium">{errorMsg}</div>}
      </div>
    </div>
  );
}
