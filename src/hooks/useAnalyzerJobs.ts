import { useEffect, useState } from 'react';
import type { AnalyzerJob } from '../services/analyzerService';
import { getJobs, subscribeToJobs } from '../services/analyzerService';

export function useAnalyzerJobs() {
  const [jobs, setJobs] = useState<AnalyzerJob[]>(() => getJobs());

  useEffect(() => {
    return subscribeToJobs(setJobs);
  }, []);

  return jobs;
}

export default useAnalyzerJobs;
