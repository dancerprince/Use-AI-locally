import { useCallback, useEffect, useRef, useState } from 'react';
import { api, streamPull } from '../api/client';
import type { PullJob } from '../api/types';

/**
 * Tracks model downloads. Re-attaches to in-flight jobs on mount and
 * reconnects the progress stream if it drops before the job is done.
 */
export function usePullProgress(onFinished?: (job: PullJob) => void) {
  const [jobs, setJobs] = useState<Record<string, PullJob>>({});
  const watching = useRef(new Set<string>());
  const ctrl = useRef(new AbortController());
  const finished = useRef(onFinished);
  finished.current = onFinished;

  const watch = useCallback(async (jobId: string) => {
    if (watching.current.has(jobId)) return;
    watching.current.add(jobId);
    let attempts = 0;
    while (!ctrl.current.signal.aborted && attempts < 20) {
      try {
        for await (const snap of streamPull(jobId, ctrl.current.signal)) {
          attempts = 0;
          setJobs((j) => ({ ...j, [snap.id]: snap }));
          if (snap.done) {
            watching.current.delete(jobId);
            finished.current?.(snap);
            return;
          }
        }
      } catch (e) {
        if (ctrl.current.signal.aborted) return;
        if (e instanceof Error && 'status' in e && (e as { status: number }).status === 404) break;
      }
      attempts += 1;
      await new Promise((r) => setTimeout(r, Math.min(1000 * attempts, 5000)));
    }
    watching.current.delete(jobId);
  }, []);

  useEffect(() => {
    ctrl.current = new AbortController();
    const c = ctrl.current;
    const w = watching.current;
    api.models
      .pulls()
      .then((list) => {
        setJobs(Object.fromEntries(list.map((j) => [j.id, j])));
        list.filter((j) => !j.done).forEach((j) => void watch(j.id));
      })
      .catch(() => {});
    return () => {
      c.abort();
      w.clear();
    };
  }, [watch]);

  const start = useCallback(
    async (name: string) => {
      const job = await api.models.pull(name);
      setJobs((j) => ({ ...j, [job.job_id]: { ...job, id: job.job_id } }));
      void watch(job.job_id);
      return job;
    },
    [watch],
  );

  const cancel = useCallback(async (jobId: string) => {
    const snap = await api.models.cancel(jobId);
    setJobs((j) => ({ ...j, [jobId]: snap }));
  }, []);

  const dismiss = useCallback((jobId: string) => {
    setJobs(({ [jobId]: _drop, ...rest }) => rest);
  }, []);

  return { jobs: Object.values(jobs), start, cancel, dismiss };
}
