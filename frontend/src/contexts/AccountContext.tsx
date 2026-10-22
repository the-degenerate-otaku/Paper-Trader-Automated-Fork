import { apiFetch, remoteMode } from "../connection";
import React, { createContext, useContext, useReducer, useEffect, useCallback } from 'react';
import type { AccountSummary, AccountsResponse } from '../types/account';

const API_BASE_URL = '/api/v1/trading';

export interface AccountContextState {
  selectedAccount: AccountSummary | null;
  availableAccounts: AccountSummary[];
  isLoading: boolean;
  error: string | null;
  isInitialized: boolean;
}

export interface AccountContextActions {
  selectAccount: (account: AccountSummary) => void;
  clearAccount: () => void;
  refreshAccounts: () => Promise<void>;
  setError: (error: string | null) => void;
  clearError: () => void;
}

export type AccountContextValue = AccountContextState & AccountContextActions;

type AccountAction =
  | { type: 'SET_LOADING'; payload: boolean }
  | { type: 'SET_ERROR'; payload: string | null }
  | { type: 'SET_ACCOUNTS'; payload: AccountSummary[] }
  | { type: 'SELECT_ACCOUNT'; payload: AccountSummary }
  | { type: 'CLEAR_ACCOUNT' }
  | { type: 'SET_INITIALIZED'; payload: boolean };

const initialState: AccountContextState = {
  selectedAccount: null,
  availableAccounts: [],
  isLoading: false,
  error: null,
  isInitialized: false,
};

function accountReducer(state: AccountContextState, action: AccountAction): AccountContextState {
  switch (action.type) {
    case 'SET_LOADING':
      return { ...state, isLoading: action.payload };
    case 'SET_ERROR':
      return { ...state, error: action.payload, isLoading: false };
    case 'SET_ACCOUNTS':
      return { ...state, availableAccounts: action.payload, isLoading: false, error: null };
    case 'SELECT_ACCOUNT':
      return { ...state, selectedAccount: action.payload, error: null };
    case 'CLEAR_ACCOUNT':
      return { ...state, selectedAccount: null };
    case 'SET_INITIALIZED':
      return { ...state, isInitialized: action.payload };
    default:
      return state;
  }
}

const SELECTED_ACCOUNT_KEY = 'openPaperTrading_selectedAccount';
const ACCOUNTS_CACHE_KEY = 'openPaperTrading_accountsCache';
const CACHE_EXPIRY_KEY = 'openPaperTrading_cacheExpiry';
const CACHE_DURATION = 5 * 60 * 1000;

const saveToLocalStorage = (key: string, data: unknown) => {
  if (remoteMode) return;
  try {
    localStorage.setItem(key, JSON.stringify(data));
  } catch {
    return;
  }
};

const loadFromLocalStorage = (key: string) => {
  if (remoteMode) return null;
  try {
    const item = localStorage.getItem(key);
    return item ? JSON.parse(item) : null;
  } catch {
    return null;
  }
};

const isCacheValid = (): boolean => {
  const expiry = loadFromLocalStorage(CACHE_EXPIRY_KEY);
  return expiry ? new Date().getTime() < expiry : false;
};

const fetchAccounts = async (): Promise<AccountSummary[]> => {
  const response = await apiFetch(`${API_BASE_URL}/accounts`);
  if (!response.ok) {
    throw new Error(`Failed to fetch accounts: ${response.status} ${response.statusText}`);
  }
  
  const data: AccountsResponse = await response.json();
  if (!data.success) {
    throw new Error(data.message || 'Failed to fetch accounts');
  }
  
  return data.accounts;
};

const validateAccountExists = async (accountId: string): Promise<boolean> => {
  try {
    const response = await apiFetch(`${API_BASE_URL}/accounts/${accountId}/balance`);
    return response.ok;
  } catch {
    return false;
  }
};

const AccountContext = createContext<AccountContextValue | undefined>(undefined);

interface AccountProviderProps {
  children: React.ReactNode;
}

export const AccountProvider: React.FC<AccountProviderProps> = ({ children }) => {
  const [state, dispatch] = useReducer(accountReducer, initialState);

  useEffect(() => {
    const loadCachedData = async () => {
      dispatch({ type: 'SET_LOADING', payload: true });
      
      try {

        if (isCacheValid()) {
          const cachedAccounts = loadFromLocalStorage(ACCOUNTS_CACHE_KEY);
          if (cachedAccounts && Array.isArray(cachedAccounts)) {
            dispatch({ type: 'SET_ACCOUNTS', payload: cachedAccounts });
          }
        } else {

          const accounts = await fetchAccounts();
          dispatch({ type: 'SET_ACCOUNTS', payload: accounts });

          saveToLocalStorage(ACCOUNTS_CACHE_KEY, accounts);
          saveToLocalStorage(CACHE_EXPIRY_KEY, new Date().getTime() + CACHE_DURATION);
        }

        const savedAccount = loadFromLocalStorage(SELECTED_ACCOUNT_KEY);
        if (savedAccount) {
          const exists = await validateAccountExists(savedAccount.id);
          if (exists) {
            dispatch({ type: 'SELECT_ACCOUNT', payload: savedAccount });
          } else {

            localStorage.removeItem(SELECTED_ACCOUNT_KEY);
            dispatch({ type: 'SET_ERROR', payload: 'Previously selected account no longer exists' });
          }
        }
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : 'Failed to load account data';
        dispatch({ type: 'SET_ERROR', payload: errorMessage });

      } finally {
        dispatch({ type: 'SET_INITIALIZED', payload: true });
      }
    };

    loadCachedData();
  }, []);

  const selectAccount = useCallback((account: AccountSummary) => {
    dispatch({ type: 'SELECT_ACCOUNT', payload: account });
    saveToLocalStorage(SELECTED_ACCOUNT_KEY, account);
    dispatch({ type: 'SET_ERROR', payload: null });

  }, []);

  const clearAccount = useCallback(() => {
    dispatch({ type: 'CLEAR_ACCOUNT' });
    localStorage.removeItem(SELECTED_ACCOUNT_KEY);
  }, []);

  const refreshAccounts = useCallback(async () => {
    dispatch({ type: 'SET_LOADING', payload: true });
    
    try {
      const accounts = await fetchAccounts();
      dispatch({ type: 'SET_ACCOUNTS', payload: accounts });

      saveToLocalStorage(ACCOUNTS_CACHE_KEY, accounts);
      saveToLocalStorage(CACHE_EXPIRY_KEY, new Date().getTime() + CACHE_DURATION);

      if (state.selectedAccount) {
        const updatedAccount = accounts.find(account => account.id === state.selectedAccount?.id);
        if (updatedAccount) {
          selectAccount(updatedAccount);
        } else {
          clearAccount();
          dispatch({ type: 'SET_ERROR', payload: 'Selected account was deleted' });
        }
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to refresh accounts';
      dispatch({ type: 'SET_ERROR', payload: errorMessage });

    }
  }, [state.selectedAccount, selectAccount, clearAccount]);

  const setError = useCallback((error: string | null) => {
    dispatch({ type: 'SET_ERROR', payload: error });
  }, []);

  const clearError = useCallback(() => {
    dispatch({ type: 'SET_ERROR', payload: null });
  }, []);

  const contextValue: AccountContextValue = {

    selectedAccount: state.selectedAccount,
    availableAccounts: state.availableAccounts,
    isLoading: state.isLoading,
    error: state.error,
    isInitialized: state.isInitialized,

    selectAccount,
    clearAccount,
    refreshAccounts,
    setError,
    clearError,
  };

  return (
    <AccountContext.Provider value={contextValue}>
      {children}
    </AccountContext.Provider>
  );
};

export const useAccountContext = (): AccountContextValue => {
  const context = useContext(AccountContext);
  if (context === undefined) {
    throw new Error('useAccountContext must be used within an AccountProvider');
  }
  return context;
};

export const useRequireAccount = (): AccountSummary => {
  const { selectedAccount } = useAccountContext();
  if (!selectedAccount) {
    throw new Error('No account selected. Please select an account first.');
  }
  return selectedAccount;
};

export default AccountContext;
