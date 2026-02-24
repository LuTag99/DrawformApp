import { useEffect, useState } from 'react';
import type { ReconstructJob } from '../services/reconstructService';
import { getReconstructJobs, subscribeToReconstructJobs } from '../services/reconstructService';

export function useReconstructJobs(): ReconstructJob[] {
  const [jobs, setJobs] = useState<ReconstructJob[]>(() => getReconstructJobs());

  useEffect(() => {
    return subscribeToReconstructJobs(setJobs);
  }, []);

  return jobs;
}

export default useReconstructJobs;
