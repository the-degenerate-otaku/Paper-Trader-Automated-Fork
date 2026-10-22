import axios from 'axios';
import type { 
  AccountsResponse, 
  CreateAccountRequest, 
  CreateAccountResponse, 
  DeleteAccountResponse,
  AccountBalance,
  AccountSummary
} from '../types/account';

const baseURL = '/api/v1/trading';

const apiClient = axios.create({
  baseURL,
  headers: {
    'Content-Type': 'application/json',
  },
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {


    if (!error.response) {
      throw new Error('Network error - please check your connection');
    }

    if (error.response.status >= 500) {
      throw new Error('Server error - please try again later');
    }

    if (error.response.status >= 400) {
      const message = error.response.data?.message || error.response.data?.detail || 'Request failed';
      throw new Error(message);
    }

    throw error;
  }
);

export const getAllAccounts = async (): Promise<AccountsResponse> => {
  const response = await apiClient.get('/accounts');
  return response.data;
};

export const createAccount = async (accountData: CreateAccountRequest): Promise<CreateAccountResponse> => {
  const response = await apiClient.post('/accounts', accountData);
  return response.data;
};

export const deleteAccount = async (accountId: string): Promise<DeleteAccountResponse> => {
  const response = await apiClient.delete(`/accounts/${accountId}`);
  return response.data;
};

export const getAccountBalance = async (accountId: string): Promise<AccountBalance> => {
  const response = await apiClient.get(`/accounts/${accountId}/balance`);
  return response.data;
};

export const getAccountDetails = async (accountId: string): Promise<{ success: boolean; account: AccountSummary; message: string }> => {
  const response = await apiClient.get(`/accounts/${accountId}`);
  return response.data;
};

export const getAccountsSummary = async (): Promise<{
  success: boolean;
  summary: {
    total_count: number;
    total_starting_balance: number;
    total_current_balance: number;
    total_balance_change: number;
  };
  message: string;
}> => {
  const response = await apiClient.get('/accounts/summary');
  return response.data;
};

export default apiClient;
