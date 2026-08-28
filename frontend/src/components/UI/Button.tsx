import React, { type ButtonHTMLAttributes } from 'react';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'ghost';
  size?: 'sm' | 'md' | 'icon';
}

export const Button: React.FC<ButtonProps> = ({ 
  children, 
  variant = 'primary', 
  size = 'md', 
  className = '', 
  ...props 
}) => {
  const classes = `btn btn-${variant} btn-${size} ${className}`;
  return (
    <button className={classes.trim()} {...props}>
      {children}
    </button>
  );
};
